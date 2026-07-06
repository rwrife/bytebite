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
from .identify import HEAD_SIZE, identify
from .peek import DEFAULT_BYTES, peek_result_dict, render_peek
from .render import quiet_line, render_identification, result_dict, to_json

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
        "file",
        nargs="?",
        help="path to the file to identify, or '-' for stdin (omit to show help)",
    )
    _add_output_flags(parser)
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

    if json_out:
        print(to_json(result_dict(best, source=source)))
    elif quiet:
        line = quiet_line(best)
        if line:
            print(line)
    else:
        alternatives = matches[1:3] if len(matches) > 1 else None
        print(render_identification(best, source=source, alternatives=alternatives))
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

    if args.json:
        print(
            to_json(
                peek_result_dict(
                    head, best, bytes_shown=args.bytes, source=display
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Route the ``peek`` subcommand before the top-level parser runs, so the
    # bare ``bytebite <file>`` identify form stays the zero-ceremony default.
    if argv and argv[0] == "peek":
        return _peek_file(argv[1:])

    # ``bytebite -`` reads from stdin. A lone ``-`` would be misread by argparse
    # as an optional, so swap in the sentinel (as peek does) and let the parser
    # collect any ``--json`` / ``--quiet`` flags alongside it.
    normalized = [_STDIN_TOKEN if a == STDIN_ARG else a for a in argv]
    parser = build_parser()
    args = parser.parse_args(normalized)

    if args.file is None:
        # A bare invocation stays friendly: print help, exit 0.
        parser.print_help()
        return EXIT_OK

    path = STDIN_ARG if args.file == _STDIN_TOKEN else args.file
    return _identify_file(path, json_out=args.json, quiet=args.quiet)


if __name__ == "__main__":  # pragma: no cover - exercised via python -m
    raise SystemExit(main())
