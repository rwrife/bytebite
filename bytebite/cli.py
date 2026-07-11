"""Command-line entry point for bytebite.

M2 wires up the core identification path: ``bytebite <file>`` reads the file's
head, matches it against the signature registry, and prints the format name,
category, confidence and the matched magic-byte range. Unknown files print a
clear message and exit non-zero.

M3 adds the ``peek`` subcommand: ``bytebite peek <file>`` renders an annotated
hex view of the header with the recognised magic-byte range highlighted and
labelled (``--bytes N`` controls how much is shown). ``--json`` output lands in
M5; the plumbing here is kept deliberately small so it slots in cleanly.

M4 adds stdin support: ``bytebite -`` (and ``bytebite peek -``) read the blob
from standard input so bytebite composes in pipelines (``cat x | bytebite -``).

M5 makes bytebite a good pipeline citizen: ``--json`` emits one stable,
newline-terminated JSON line (schema versioned, see README) for both ``identify``
and ``peek``; ``--quiet`` prints just the format name (or nothing on an unknown)
for ``name=$(bytebite f -q)`` style use. Colour is never emitted in either mode.

The ``explain`` subcommand (issue #7) is the pocket-reference path: ``bytebite
explain <format>`` prints a *known format's* magic bytes and documented header
layout without needing a file. It reuses the signature registry and the M6
field layouts; ``--json`` emits the same reference as one stable line.

Exit codes (stabilised in M5):
    0  file identified
    1  file read but not identified
    2  usage / I/O error

``peek`` is a *viewer*: a successful render exits 0 even for an unknown blob,
while ``--quiet``/``--json`` on ``peek`` still surface identification via the
payload. Use bare ``bytebite <file>`` when you want the exit code to gate on
identification.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, Tuple

from . import __version__
from .container import ContainerKind, detect_container
from .explain import explain as explain_format
from .explain import explain_dict, render_explain
from .find import (
    PredicateError,
    find_matches,
    find_result_dict,
    parse_predicate,
)
from .identify import HEAD_SIZE, identify
from .peek import DEFAULT_BYTES, peek_result_dict, render_peek
from .render import (
    SCHEMA_VERSION,
    quiet_line,
    render_identification,
    result_dict,
    to_json,
)
from .signatures import all_signatures

PROG = "bytebite"
DESCRIPTION = "A pocket detective for mystery files: identify a binary and peek at its header."
EPILOG = "See PLAN.md for the roadmap. Use --json for scriptable output; exit 0=identified, 1=unknown, 2=error."

EXIT_OK = 0
EXIT_UNIDENTIFIED = 1
EXIT_ERROR = 2

STDIN_DISPLAY = "<stdin>"
STDIN_ARG = "-"
# Internal placeholder so argparse doesn't treat a lone ``-`` as an optional.
_STDIN_TOKEN = "\x00bytebite-stdin\x00"


def _is_stdin(path: str) -> bool:
    """Return ``True`` when ``path`` is the stdin sentinel (``-``)."""
    return path == STDIN_ARG


def _display_name(path: str) -> str:
    """Human label for a source path (``-`` becomes ``<stdin>``)."""
    return STDIN_DISPLAY if _is_stdin(path) else path


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--json`` / ``--quiet`` scripting flags to ``parser``.

    Kept in one place so ``identify`` and ``peek`` expose an identical contract.
    ``--json`` and ``--quiet`` are mutually exclusive (JSON is already the
    machine format; asking for both is a usage error).
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON line (schema in README)",
    )
    group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="machine-only: print just the format name (nothing if unknown)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser.

    ``bytebite <file>`` identifies a file (the default action). ``bytebite peek
    <file>`` renders the annotated hex view. Subcommands are added via a
    subparser, but the bare ``<file>`` form is preserved for the common case by
    routing in :func:`main` before argparse sees a subcommand name.
    """
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="list every known format (and which have field-level header detail) and exit",
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="path to the file to identify, or '-' for stdin (omit to show help)",
    )
    _add_output_flags(parser)
    return parser


def build_explain_parser() -> argparse.ArgumentParser:
    """Parser for the ``explain`` subcommand (the file-less reference)."""
    parser = argparse.ArgumentParser(
        prog=f"{PROG} explain",
        description="Print a known format's magic bytes and documented header layout (no file needed).",
    )
    parser.add_argument(
        "format",
        help="format to explain, e.g. 'png', 'elf', 'zip', 'wav' (also accepts '.png' or the full name)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the reference as one machine-readable JSON line (schema in README)",
    )
    return parser


def build_find_parser() -> argparse.ArgumentParser:
    """Parser for the ``find`` subcommand (fuzzy structured header search)."""
    parser = argparse.ArgumentParser(
        prog=f"{PROG} find",
        description=(
            "Search files for header fields matching a value, e.g. "
            "`bytebite find --field width=1920 *.bin`."
        ),
    )
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "field predicate; repeatable (all must match). Operators: "
            "= (exact, matches raw value or enum label), >=, <=, >, < (numeric)"
        ),
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="one or more files to search (shell globs expand to these)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit matches as one machine-readable JSON line (schema in README)",
    )
    return parser


def build_peek_parser() -> argparse.ArgumentParser:
    """Parser for the ``peek`` subcommand."""
    parser = argparse.ArgumentParser(
        prog=f"{PROG} peek",
        description="Annotated hex view of a file's header, magic bytes labelled.",
    )
    parser.add_argument(
        "file",
        help="path to the file to peek at, or '-' for stdin",
    )
    parser.add_argument(
        "-n",
        "--bytes",
        type=int,
        default=DEFAULT_BYTES,
        metavar="N",
        help=f"how many leading bytes to show (default: {DEFAULT_BYTES})",
    )
    _add_output_flags(parser)
    return parser


def _read_head(path: str) -> Tuple[Optional[bytes], int]:
    """Read a source's head, returning ``(head, exit_code)``.

    ``path`` may be a filesystem path or ``-`` for standard input. On success
    ``head`` is the bytes and the code is :data:`EXIT_OK`; on failure ``head``
    is ``None`` and the code is :data:`EXIT_ERROR` (a message has already been
    printed to stderr).
    """
    if _is_stdin(path):
        try:
            return sys.stdin.buffer.read(HEAD_SIZE), EXIT_OK
        except OSError as exc:  # pragma: no cover - stdin read errors are rare
            print(f"{PROG}: <stdin>: {exc.strerror or exc}", file=sys.stderr)
            return None, EXIT_ERROR
    try:
        with open(path, "rb") as fh:
            return fh.read(HEAD_SIZE), EXIT_OK
    except FileNotFoundError:
        print(f"{PROG}: {path}: no such file", file=sys.stderr)
    except IsADirectoryError:
        print(f"{PROG}: {path}: is a directory", file=sys.stderr)
    except OSError as exc:
        print(f"{PROG}: {path}: {exc.strerror or exc}", file=sys.stderr)
    return None, EXIT_ERROR


def _container_for(match, source: str):
    """Return a :class:`ContainerKind` when ``match`` is a ZIP worth peeking into.

    Container detection needs random access to the archive's central directory,
    so it only runs for real files (not stdin) whose best match is the ZIP local
    file header. Any other match — or an unreadable/plain archive — yields
    ``None`` and the identification is reported unchanged.
    """
    if match is None or _is_stdin(source):
        return None
    if match.name != "ZIP archive":
        return None
    return detect_container(source)


def _identify_file(path: str, *, json_out: bool = False, quiet: bool = False) -> int:
    """Identify ``path`` (or stdin when ``-``) and print. Returns exit code.

    ``json_out`` emits one JSON line (schema in README); ``quiet`` prints just
    the format name (empty on unknown). Both suppress the human block and any
    colour. The exit code is the contract either way: 0 identified, 1 unknown,
    2 read/usage error.
    """
    head, code = _read_head(path)
    if head is None:
        return code

    matches = identify(head)
    best = matches[0] if matches else None
    source = _display_name(path)
    container = _container_for(best, path)

    if json_out:
        print(to_json(result_dict(best, source=source, container=container)))
    elif quiet:
        line = quiet_line(best)
        if line:
            print(line)
    else:
        alternatives = matches[1:3] if len(matches) > 1 else None
        print(
            render_identification(
                best, source=source, alternatives=alternatives, container=container
            )
        )
    return EXIT_OK if best is not None else EXIT_UNIDENTIFIED


def _peek_file(argv: Sequence[str]) -> int:
    """Handle ``bytebite peek <file> [--bytes N] [--json|--quiet]``.

    ``<file>`` may be ``-`` (stdin). ``peek`` is a viewer: a successful render
    exits 0 even for an unknown blob. ``--json`` emits the peek payload (dump
    metadata + identification + labelled spans); ``--quiet`` prints just the
    identified format name (nothing if unknown).
    """
    # A bare ``-`` (stdin) at the end of the peek args would be misread by
    # argparse as an unknown optional; swap in a sentinel we translate back.
    normalized = [_STDIN_TOKEN if a == STDIN_ARG else a for a in argv]
    args = build_peek_parser().parse_args(normalized)
    source = STDIN_ARG if args.file == _STDIN_TOKEN else args.file

    head, code = _read_head(source)
    if head is None:
        return code

    matches = identify(head)
    best = matches[0] if matches else None
    display = _display_name(source)
    container = _container_for(best, source)

    if args.json:
        print(
            to_json(
                peek_result_dict(
                    head, best, bytes_shown=args.bytes, source=display,
                    container=container,
                )
            )
        )
    elif args.quiet:
        line = quiet_line(best)
        if line:
            print(line)
    else:
        print(
            render_peek(
                head,
                best,
                bytes_shown=args.bytes,
                source=display,
            )
        )
    # peek is a viewer: rendering succeeded, so exit 0 even for unknown blobs.
    return EXIT_OK


def _explain_format(argv: Sequence[str]) -> int:
    """Handle ``bytebite explain <format> [--json]``. Returns an exit code.

    Resolves the format token forgivingly (``png`` / ``.png`` / ``PNG image``)
    and prints its magic bytes + documented header layout. An ambiguous or
    unknown token exits :data:`EXIT_ERROR` with a helpful hint on stderr, so
    ``explain`` fails loudly (unlike ``peek``, which is a viewer). ``--json``
    emits the reference payload; there is no field data to hide, so no
    ``--quiet`` here.
    """
    args = build_explain_parser().parse_args(argv)
    info, candidates, status = explain_format(args.format)

    if info is None:
        if status == "ambiguous":
            hint = ", ".join(candidates)
            print(
                f"{PROG}: explain: {args.format!r} is ambiguous. "
                f"Did you mean: {hint}?",
                file=sys.stderr,
            )
        elif candidates:
            hint = ", ".join(candidates)
            print(
                f"{PROG}: explain: unknown format {args.format!r}. "
                f"Did you mean: {hint}?",
                file=sys.stderr,
            )
        else:
            print(
                f"{PROG}: explain: unknown format {args.format!r}. "
                f"Try `{PROG} --list-formats` to see what's known.",
                file=sys.stderr,
            )
        return EXIT_ERROR

    if args.json:
        print(to_json(explain_dict(info)))
    else:
        print(render_explain(info))
    return EXIT_OK


def _find_files(argv: Sequence[str]) -> int:
    """Handle ``bytebite find --field NAME=VALUE ... FILE ...``. Returns a code.

    Identifies each file and keeps those whose decoded header fields satisfy
    every ``--field`` predicate (see :mod:`bytebite.find`). A malformed
    predicate is a usage error (exit 2); an empty result is exit 1 (nothing
    matched, like an unidentified file); at least one match is exit 0. ``--json``
    emits the matches as one stable line.
    """
    args = build_find_parser().parse_args(argv)

    try:
        predicates = [parse_predicate(clause) for clause in args.fields]
    except PredicateError as exc:
        print(f"{PROG}: find: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not predicates:
        print(
            f"{PROG}: find: need at least one --field NAME=VALUE predicate",
            file=sys.stderr,
        )
        return EXIT_ERROR

    matches = find_matches(args.files, predicates)

    if args.json:
        print(to_json(find_result_dict(matches, predicates)))
    else:
        for match in matches:
            print(match.summary())
        if not matches:
            query = " ".join(p.describe() for p in predicates)
            print(
                f"{PROG}: find: no files matched {query!r}",
                file=sys.stderr,
            )
    return EXIT_OK if matches else EXIT_UNIDENTIFIED


def _list_formats(*, json_out: bool = False) -> int:
    """Print every known format and whether it has field-level detail (M6).

    Deduplicates by format name (several signatures can share a name, e.g. the
    two GIF versions), sorts by category then name for a stable, skimmable list,
    and marks the formats that decode individual header fields. ``--json`` emits
    one machine-readable line for tooling/completions. Always exits 0.
    """
    # Collapse duplicate names; a name has field detail if any of its signatures
    # declares a field layout.
    by_name: dict = {}
    for sig in all_signatures():
        entry = by_name.setdefault(
            sig.name,
            {"name": sig.name, "category": sig.category, "fields": False},
        )
        if sig.has_fields:
            entry["fields"] = True
    formats = sorted(by_name.values(), key=lambda e: (e["category"], e["name"]))

    if json_out:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "tool": PROG,
            "formats": formats,
        }
        print(to_json(payload))
        return EXIT_OK

    with_detail = sum(1 for e in formats if e["fields"])
    print(
        f"{PROG} knows {len(formats)} formats "
        f"({with_detail} with field-level header detail):"
    )
    name_w = max(len(e["name"]) for e in formats)
    for e in formats:
        mark = "• fields" if e["fields"] else ""
        print(f"  {e['name']:<{name_w}}  {e['category']:<10} {mark}".rstrip())
    print("\n'• fields' formats decode individual header fields in `bytebite peek`.")
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Route the ``peek`` subcommand before the top-level parser runs, so the
    # bare ``bytebite <file>`` identify form stays the zero-ceremony default.
    if argv and argv[0] == "peek":
        return _peek_file(argv[1:])

    # ``explain`` is the file-less reference path; route it the same way.
    if argv and argv[0] == "explain":
        return _explain_format(argv[1:])

    # ``find`` is the fuzzy structured header search (issue #9).
    if argv and argv[0] == "find":
        return _find_files(argv[1:])

    # ``bytebite -`` reads from stdin. A lone ``-`` would be misread by argparse
    # as an optional, so swap in the sentinel (as peek does) and let the parser
    # collect any ``--json`` / ``--quiet`` flags alongside it.
    normalized = [_STDIN_TOKEN if a == STDIN_ARG else a for a in argv]
    parser = build_parser()
    args = parser.parse_args(normalized)

    if args.list_formats:
        # A registry listing, independent of any input file.
        return _list_formats(json_out=args.json)

    if args.file is None:
        # A bare invocation stays friendly: print help, exit 0.
        parser.print_help()
        return EXIT_OK

    path = STDIN_ARG if args.file == _STDIN_TOKEN else args.file
    return _identify_file(path, json_out=args.json, quiet=args.quiet)


if __name__ == "__main__":  # pragma: no cover - exercised via python -m
    raise SystemExit(main())
