"""Command-line entry point for bytebite.

M1 scope: a living skeleton. ``bytebite --version`` prints the version and
``bytebite`` with no arguments prints help. The real subcommands (identify,
``peek``) are stubbed here and land in M2/M3.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from . import __version__

PROG = "bytebite"
DESCRIPTION = "A pocket detective for mystery files: identify a binary and peek at its header."
EPILOG = (
    "Subcommands (identify, peek) are not implemented yet — this is the M1 "
    "scaffold. See PLAN.md for the roadmap."
)


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
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI.

    Returns a process exit code. With no arguments we print help and exit 0 so
    that a bare ``bytebite`` invocation is friendly rather than an error.
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = build_parser()
    args = parser.parse_args(argv)

    # No subcommands wired up yet: a bare invocation just shows help.
    del args  # nothing to dispatch on in M1
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via python -m
    raise SystemExit(main())
