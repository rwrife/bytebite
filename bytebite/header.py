"""The ``header`` subcommand — pure parsed-header output (issue #23).

Milestone 6 taught ``peek`` to decode individual header fields; this module
exposes that decoded structure on its own, with no hex art and no prose, so
scripts and downstream tools can consume it directly.

``bytebite header <file>`` identifies the file and prints its decoded header
fields (name, byte range, value, human label). ``--json`` (the natural machine
shape for this subcommand) emits one stable line::

    {
      "schema_version": int,
      "tool": "bytebite",
      "source": str,
      "identified": bool,
      "format": str|null,
      "category": str|null,
      "magic": {"offset": int, "end": int, "hex": str} | null,
      "fields": [
        {"name": str, "offset": int, "end": int, "size": int,
         "type": str, "value": <decoded>, "label": str|null,
         "hex": str, "note": str}
      ]
    }

When a format has no field-layout decoder yet, ``fields`` is an empty list while
the identification stays populated — callers get a consistent shape either way.
This is the "library-in-a-CLI" seam that makes bytebite pipeline-friendly; it is
strictly read-only, local-only, and adds no dependencies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .fields import decoded_fields_for
from .identify import Match
from .render import SCHEMA_VERSION, format_hex


def _field_dicts(match: Optional[Match], data: bytes) -> List[Dict[str, Any]]:
    """Decode ``match``'s header fields from ``data`` as plain dicts.

    Returns an empty list when there is no match or the format has no field
    layout (or the header was too short to decode any field), so the JSON shape
    stays consistent for every caller.
    """
    decoded = decoded_fields_for(match.name, data) if match is not None else []
    return [
        {
            "name": d.name,
            "offset": d.offset,
            "end": d.end,
            "size": d.field.size,
            "type": d.field.type,
            "value": d.value,
            "label": d.label,
            "hex": d.raw.hex(),
            "note": d.note,
        }
        for d in decoded
    ]


def header_result_dict(
    data: bytes,
    match: Optional[Match] = None,
    *,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the machine-readable ``header --json`` payload.

    A deliberately lean shape: identification (format/category/magic) plus the
    decoded ``fields`` list — no hex dump, no spans, no prose. Reuses the field
    decoding from :mod:`bytebite.fields` and is versioned by
    :data:`~bytebite.render.SCHEMA_VERSION`.
    """
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": "bytebite",
        "source": source,
        "identified": match is not None,
        "format": match.name if match is not None else None,
        "category": match.category if match is not None else None,
        "magic": (
            {
                "offset": match.offset,
                "end": match.end,
                "hex": format_hex(match.matched_bytes),
            }
            if match is not None
            else None
        ),
        "fields": _field_dicts(match, data),
    }
    return payload


def render_header(
    data: bytes,
    match: Optional[Match] = None,
    *,
    source: Optional[str] = None,
) -> str:
    """Human-readable (but hex-free) rendering of the parsed header.

    Prints the identified format then a clean, aligned list of decoded fields.
    An unknown file says so; an identified file with no field layout says the
    identification stands but no fields are decoded — matching the empty-fields
    JSON fallback.
    """
    src = source or "<input>"
    if match is None:
        return f"{src}: unknown format — no header to parse."

    lines = [f"{match.name}  (category: {match.category})   — {src}"]
    fields = _field_dicts(match, data)
    if not fields:
        lines.append("   (no field-level header layout for this format yet)")
        return "\n".join(lines)

    name_w = max(len(f["name"]) for f in fields)
    for f in fields:
        if f["offset"] == f["end"] - 1:
            rng = f"0x{f['offset']:02x}"
        else:
            rng = f"0x{f['offset']:02x}\u20130x{f['end'] - 1:02x}"
        if f["label"] is not None:
            value = f"{f['label']} ({f['value']})"
        else:
            value = str(f["value"])
        note = f"   # {f['note']}" if f["note"] else ""
        lines.append(f"   {rng:>11}  {f['name']:<{name_w}} = {value}{note}")
    return "\n".join(lines)
