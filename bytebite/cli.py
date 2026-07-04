"""Command-line entry point for bytebite.

M2 wires up the core identification path: ``bytebite <file>`` reads the file's
head, matches it against the signature registry, and prints the format name,
category, confidence and the matched magic-byte range. Unknown files print a
clear message and exit non-zero.

The ``peek`` subcommand (annotated hex view) and ``--json`` output are stubbed /
land in M3 and M5 respectively; the plumbing here is kept deliberately small so
those slot in cleanly.

Exit codes (stabilised further in M5):
    0  file identified
    1  file read but not identified
    2  usage / I/O error
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__
from .identify import HEAD_SIZE, identify
from .render import render_identification

PROG = "bytebite"
DESCRIPTION = "A pocket detective for mystery files: identify a binary and peek at its header."
EPILOG = "See PLAN.md for the roadmap. peek/--json arrive in later milestones."

EXIT_OK = 0
EXIT_UNIDENTIFIED = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
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
        help="path to the file to identify (omit to show this help)",
    )
    return parser


def _identify_file(path: str) -> int:
    """Identify ``path`` and print the result. Returns a process exit code."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEAD_SIZE)
    except FileNotFoundError:
        print(f"{PROG}: {path}: no such file", file=sys.stderr)
        return EXIT_ERROR
    except IsADirectoryError:
        print(f"{PROG}: {path}: is a directory", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"{PROG}: {path}: {exc.strerror or exc}", file=sys.stderr)
        return EXIT_ERROR

    matches = identify(head)
    best = matches[0] if matches else None
    alternatives = matches[1:3] if len(matches) > 1 else None

    print(render_identification(best, source=path, alternatives=alternatives))
    return EXIT_OK if best is not None else EXIT_UNIDENTIFIED


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.file is None:
        # A bare invocation stays friendly: print help, exit 0.
        parser.print_help()
        return EXIT_OK

    return _identify_file(args.file)


if __name__ == "__main__":  # pragma: no cover - exercised via python -m
    raise SystemExit(main())
