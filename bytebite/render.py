"""Output formatting for bytebite.

M2 keeps this small: a friendly human-readable identification block. Colour is
opt-in and auto-disabled when stdout is not a TTY or ``NO_COLOR`` is set, so
piped/redirected output stays clean. Structured ``--json`` output arrives in
M5, but a helper to build the plain result dict lives here already so the CLI
and future JSON path share one source of truth.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from .identify import Match

# A tiny, dependency-free ANSI palette. Only what we need.
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"


def color_enabled(stream: Any = None) -> bool:
    """Decide whether to emit ANSI colour for ``stream`` (default stdout).

    Respects the ``NO_COLOR`` convention and only colours real terminals.
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _paint(text: str, *codes: str, enabled: bool) -> str:
    if not enabled or not codes:
        return text
    return "".join(codes) + text + _RESET


def format_hex(data: bytes) -> str:
    r"""Render ``data`` as spaced upper-case hex escapes, e.g. ``\x89PNG``.

    We show printable ASCII literally and everything else as ``\xNN`` so the
    matched magic reads the way people write it in docs.
    """
    out = []
    for b in data:
        if 0x20 <= b <= 0x7E and b not in (0x5C,):  # printable, excluding backslash
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def result_dict(match: Optional[Match]) -> Dict[str, Any]:
    """Build the canonical result mapping (shared with the future JSON path)."""
    if match is None:
        return {"identified": False, "match": None}
    return {
        "identified": True,
        "match": {
            "name": match.name,
            "category": match.category,
            "confidence": match.confidence,
            "description": match.description,
            "offset": match.offset,
            "end": match.end,
            "magic": format_hex(match.matched_bytes),
        },
    }


def render_identification(
    match: Optional[Match],
    *,
    source: str,
    alternatives: Optional[List[Match]] = None,
    use_color: Optional[bool] = None,
) -> str:
    """Return the human-readable identification block for ``match``.

    ``source`` is a display label for the input (a path, or ``"<stdin>"``).
    ``alternatives`` are any other matches worth mentioning (already excluding
    the best one). ``use_color`` overrides auto-detection when given.
    """
    enabled = color_enabled() if use_color is None else use_color

    if match is None:
        head = _paint("?", _BOLD, enabled=enabled)
        return (
            f"{head} unidentified — no known signature matched {source}\n"
            f"   (bytebite currently knows the common seed formats; see PLAN.md)"
        )

    name = _paint(match.name, _BOLD, _CYAN, enabled=enabled)
    pct = f"{round(match.confidence * 100)}%"
    pct_p = _paint(pct, _GREEN, enabled=enabled)
    magic = format_hex(match.matched_bytes)
    rng = f"0x{match.offset:02x}"
    if match.end - match.offset > 1:
        rng = f"0x{match.offset:02x}–0x{match.end - 1:02x}"

    lines = [
        f"🔍 {name}  (category: {match.category})   confidence: {pct_p}",
        f"   matched magic {magic} at offset {rng}",
    ]
    if match.description:
        lines.append(f"   → {match.description}")

    if alternatives:
        alt_names = ", ".join(
            f"{m.name} ({round(m.confidence * 100)}%)" for m in alternatives
        )
        lines.append(_paint(f"   other candidates: {alt_names}", _DIM, enabled=enabled))

    return "\n".join(lines)
