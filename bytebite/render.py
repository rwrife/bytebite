"""Output formatting for bytebite.

M2 keeps this small: a friendly human-readable identification block. Colour is
opt-in and auto-disabled when stdout is not a TTY or ``NO_COLOR`` is set, so
piped/redirected output stays clean.

M5 turns bytebite into a good pipeline citizen. The ``result_dict`` helper is
the single source of truth for a machine-readable identification, and
:func:`to_json` serialises it as one stable, newline-terminated line. Colour is
never emitted in ``--json`` or ``--quiet`` modes, and exit codes are stabilised
in the CLI (0 = identified, 1 = unknown, 2 = error). The JSON schema is
versioned via :data:`SCHEMA_VERSION` so downstream scripts can pin to it.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from .container import ContainerKind
from .identify import Match

# Bumped whenever the JSON shape changes in a way scripts would notice. The
# value is surfaced in every ``--json`` payload as ``schema_version`` so
# consumers can pin to (or branch on) a known contract. Documented in README.
#
# v2 adds the optional ``container`` object to a match payload: when a ZIP-based
# file is recognised as a specific format (docx/jar/apk/epub…), the real type is
# reported alongside the plain ZIP identification. The field is ``null`` for
# non-container matches, so v1 consumers that ignore unknown keys keep working.
SCHEMA_VERSION = 2

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


def result_dict(
    match: Optional[Match],
    *,
    source: Optional[str] = None,
    container: Optional[ContainerKind] = None,
) -> Dict[str, Any]:
    """Build the canonical identification mapping (the ``--json`` payload).

    This is the single source of truth for machine-readable output. ``source``
    (a path or ``"<stdin>"``) is included when given so a batch of JSON lines
    stays self-describing. The shape is versioned by :data:`SCHEMA_VERSION`.

    Schema::

        {
          "schema_version": 1,
          "tool": "bytebite",
          "source": "mystery.blob" | "<stdin>" | null,
          "identified": true | false,
          "match": null | {
            "name": str, "category": str, "confidence": float (0..1),
            "description": str, "offset": int, "end": int, "magic": str,
            "container": null | {
              "name": str, "extension": str, "description": str
            }
          }
        }
    """
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": "bytebite",
        "source": source,
        "identified": match is not None,
        "match": None,
    }
    if match is not None:
        payload["match"] = {
            "name": match.name,
            "category": match.category,
            "confidence": match.confidence,
            "description": match.description,
            "offset": match.offset,
            "end": match.end,
            "magic": format_hex(match.matched_bytes),
            "container": (
                {
                    "name": container.name,
                    "extension": container.extension,
                    "description": container.description,
                }
                if container is not None
                else None
            ),
        }
    return payload


def to_json(payload: Dict[str, Any]) -> str:
    """Serialise a result mapping as one compact, stable JSON line.

    Keys are *not* sorted — insertion order is deliberate and stable, so the
    output reads naturally (``schema_version`` first) while staying diffable.
    A trailing newline is *not* added here; the CLI prints via ``print`` which
    adds exactly one, keeping ``bytebite ... --json | jq`` and line-based tools
    happy.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def quiet_line(match: Optional[Match]) -> str:
    """Machine-only one-liner for ``--quiet``: just the format name.

    Returns the identified format's name (e.g. ``PNG image``) or an empty
    string when nothing matched. The empty line keeps the *presence* of output
    aligned with the exit code (1 = unknown) without printing chatter, so
    ``name=$(bytebite f --quiet)`` is clean.
    """
    return match.name if match is not None else ""


def render_identification(
    match: Optional[Match],
    *,
    source: str,
    alternatives: Optional[List[Match]] = None,
    container: Optional[ContainerKind] = None,
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

    if container is not None:
        looks = _paint(
            f".{container.extension}", _BOLD, _CYAN, enabled=enabled
        )
        lines.append(f"   📦 ZIP container → looks like a {looks} ({container.name})")
        if container.description:
            lines.append(f"      {container.description}")

    if alternatives:
        alt_names = ", ".join(
            f"{m.name} ({round(m.confidence * 100)}%)" for m in alternatives
        )
        lines.append(_paint(f"   other candidates: {alt_names}", _DIM, enabled=enabled))

    return "\n".join(lines)
