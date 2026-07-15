"""The ``diff`` subcommand — structural comparison of two files (issue #22).

Given two mystery blobs, ``bytebite diff a.bin b.bin`` identifies both and shows
*what each one is* and *how their recognised headers differ*: same format? same
magic offset? which decoded header fields agree, differ, or exist on only one
side?

This is a pure composition of the existing engine — identification
(:mod:`bytebite.identify`) plus field decoding (:mod:`bytebite.fields`) — so
there is no duplicate parsing logic. It stays strictly read-only, local-only,
and dependency-free (PLAN.md).

Field diffing
-------------
Two identified files may or may not share a format. We build the field-diff by
key (field name) over the *union* of both sides' decoded fields:

* present on both  → ``equal`` is ``True``/``False`` by comparing decoded values
* present on one   → ``equal`` is ``None`` (only-in-A or only-in-B)

Values are compared on their decoded Python value (an ``int`` width, an ``ascii``
tag, …); the human/JSON payload also carries each side's label and raw hex so a
reader sees both the semantic and the literal difference.

``--json`` shape::

    {
      "schema_version": int,
      "tool": "bytebite",
      "a": {<side>}, "b": {<side>},
      "same_format": bool,
      "same_magic_offset": bool,
      "field_diffs": [
        {"field": str, "a": <val>|null, "b": <val>|null,
         "a_label": str|null, "b_label": str|null,
         "a_hex": str|null, "b_hex": str|null, "equal": bool|null}
      ]
    }

where each ``<side>`` is::

    {"source": str, "identified": bool, "format": str|null,
     "category": str|null, "confidence": float|null,
     "magic": {"offset": int, "end": int, "hex": str}|null}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .fields import DecodedField, decoded_fields_for
from .identify import Match, identify
from .render import SCHEMA_VERSION, format_hex


@dataclass(frozen=True)
class Side:
    """One file's identification + decoded header, ready to compare or render."""

    source: str
    match: Optional[Match]
    fields: Dict[str, DecodedField]

    @property
    def identified(self) -> bool:
        return self.match is not None


def _build_side(source: str, head: bytes) -> Side:
    """Identify ``head`` and decode its header fields, keyed by field name."""
    matches = identify(head)
    best = matches[0] if matches else None
    decoded: Dict[str, DecodedField] = {}
    if best is not None:
        for d in decoded_fields_for(best.name, head):
            decoded[d.name] = d
    return Side(source=source, match=best, fields=decoded)


@dataclass(frozen=True)
class FieldDiff:
    """A single field's comparison across the two sides.

    ``equal`` is ``True``/``False`` when the field is present on both sides, and
    ``None`` when it exists on only one (only-in-A or only-in-B).
    """

    field: str
    a: Optional[DecodedField]
    b: Optional[DecodedField]

    @property
    def equal(self) -> Optional[bool]:
        if self.a is None or self.b is None:
            return None
        return self.a.value == self.b.value


def compare(a: Side, b: Side) -> List[FieldDiff]:
    """Diff two sides' decoded fields over the union of their field names.

    Order is stable: fields in A's order first, then any B-only fields in B's
    order. This keeps a same-format diff reading top-to-bottom like the header.
    """
    diffs: List[FieldDiff] = []
    seen = set()
    for name, da in a.fields.items():
        seen.add(name)
        diffs.append(FieldDiff(field=name, a=da, b=b.fields.get(name)))
    for name, db in b.fields.items():
        if name not in seen:
            diffs.append(FieldDiff(field=name, a=None, b=db))
    return diffs


def diff_sides(source_a: str, head_a: bytes, source_b: str, head_b: bytes):
    """Build both sides and their field diff. Returns ``(a, b, field_diffs)``."""
    a = _build_side(source_a, head_a)
    b = _build_side(source_b, head_b)
    return a, b, compare(a, b)


# --- rendering / payload ----------------------------------------------------


def _magic_dict(match: Optional[Match]) -> Optional[Dict[str, Any]]:
    if match is None:
        return None
    return {
        "offset": match.offset,
        "end": match.end,
        "hex": format_hex(match.matched_bytes),
    }


def _side_dict(side: Side) -> Dict[str, Any]:
    m = side.match
    return {
        "source": side.source,
        "identified": side.identified,
        "format": m.name if m is not None else None,
        "category": m.category if m is not None else None,
        "confidence": m.confidence if m is not None else None,
        "magic": _magic_dict(m),
    }


def _field_diff_dict(fd: FieldDiff) -> Dict[str, Any]:
    return {
        "field": fd.field,
        "a": fd.a.value if fd.a is not None else None,
        "b": fd.b.value if fd.b is not None else None,
        "a_label": fd.a.label if fd.a is not None else None,
        "b_label": fd.b.label if fd.b is not None else None,
        "a_hex": fd.a.raw.hex() if fd.a is not None else None,
        "b_hex": fd.b.raw.hex() if fd.b is not None else None,
        "equal": fd.equal,
    }


def diff_result_dict(a: Side, b: Side, field_diffs: List[FieldDiff]) -> Dict[str, Any]:
    """Build the machine-readable ``diff --json`` payload (schema-versioned)."""
    same_format = (
        a.identified
        and b.identified
        and a.match.name == b.match.name  # type: ignore[union-attr]
    )
    same_magic_offset = (
        a.identified and b.identified and a.match.offset == b.match.offset  # type: ignore[union-attr]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "bytebite",
        "a": _side_dict(a),
        "b": _side_dict(b),
        "same_format": same_format,
        "same_magic_offset": same_magic_offset,
        "field_diffs": [_field_diff_dict(fd) for fd in field_diffs],
    }


def _fmt_value(d: Optional[DecodedField]) -> str:
    if d is None:
        return "—"
    return d.display()


def render_diff(a: Side, b: Side, field_diffs: List[FieldDiff]) -> str:
    """Human-readable side-by-side of two files' identified structure."""
    la = a.source
    lb = b.source

    def ident_line(side: Side) -> str:
        m = side.match
        if m is None:
            return "unknown"
        pct = f"{round(m.confidence * 100)}%"
        return f"{m.name} ({m.category}, {pct})"

    lines = [f"diff  A: {la}   B: {lb}", ""]
    lines.append(f"  A  {ident_line(a)}")
    lines.append(f"  B  {ident_line(b)}")

    if a.identified and b.identified:
        if a.match.name == b.match.name:  # type: ignore[union-attr]
            lines.append("  → same format")
        else:
            lines.append("  → different formats")
    lines.append("")

    if not field_diffs:
        if a.identified and b.identified:
            lines.append("  (no decoded header fields to compare for these formats)")
        else:
            lines.append("  (at least one file is unidentified — no field comparison)")
        return "\n".join(lines)

    name_w = max(len(fd.field) for fd in field_diffs)
    a_col = [_fmt_value(fd.a) for fd in field_diffs]
    a_w = max((len(s) for s in a_col), default=1)
    lines.append(f"  {'field':<{name_w}}   {'A':<{a_w}}   B")
    lines.append(f"  {'-' * name_w}   {'-' * a_w}   -")
    for fd, av in zip(field_diffs, a_col):
        if fd.equal is None:
            marker = ">" if fd.a is not None else "<"  # only in A / only in B
        elif fd.equal:
            marker = "="
        else:
            marker = "\u2260"  # ≠
        bv = _fmt_value(fd.b)
        lines.append(f"{marker} {fd.field:<{name_w}}   {av:<{a_w}}   {bv}")
    return "\n".join(lines)
