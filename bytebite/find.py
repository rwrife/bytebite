"""Fuzzy structured header search — ``bytebite find`` (issue #9).

The original Hacker News wish that inspired bytebite was "an explorative hex
editor with fuzzy field search": point it at a directory of mystery binaries and
ask *"which of these are 1920 pixels wide?"* This module answers exactly that.

``bytebite find --field width=1920 *.bin`` identifies each file, decodes its
header fields with the same machinery as ``peek`` (see :mod:`bytebite.fields`),
and keeps the files whose decoded fields satisfy every ``--field`` predicate.

Design
------
* **Reuse, don't reinvent.** Identification is :func:`bytebite.identify.identify`
  and field decoding is :func:`bytebite.fields.decoded_fields_for` — the same
  code paths ``peek`` already trusts. ``find`` is pure orchestration on top.
* **Forgiving field names.** Predicates match a field by case-insensitive name,
  so ``--field Width=1920`` and ``--field width=1920`` both work. A field also
  matches on its enum *label* (``--field method=deflate``) as well as its raw
  value (``--field method=8``) so you can search the way you think.
* **Comparisons.** ``=`` is exact; ``>=``, ``<=``, ``>``, ``<`` compare
  numerically (only against numeric fields). Non-numeric fields simply never
  satisfy a numeric comparison, rather than erroring, so a mixed glob is fine.
* **A file matches when every predicate matches.** AND semantics keep the query
  intuitive; OR is just two runs.

``find`` never seeks deep into a file or executes anything — it reads the same
bounded head as the rest of bytebite (see PLAN.md "out of scope").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .fields import DecodedField, decoded_fields_for
from .identify import HEAD_SIZE, identify

# Comparison operators, longest first so ``>=`` is tried before ``>``.
_OPERATORS: Tuple[str, ...] = (">=", "<=", "=", ">", "<")


@dataclass(frozen=True)
class Predicate:
    """One parsed ``--field`` clause: a field name, an operator and a value."""

    name: str
    op: str
    value: str

    def describe(self) -> str:
        """Human echo of the predicate, e.g. ``width>=1920``."""
        return f"{self.name}{self.op}{self.value}"


class PredicateError(ValueError):
    """Raised when a ``--field`` clause can't be parsed."""


def parse_predicate(clause: str) -> Predicate:
    """Parse one ``name<op>value`` clause into a :class:`Predicate`.

    Recognises ``=``, ``>=``, ``<=``, ``>``, ``<`` (checked longest-first). The
    name and value are stripped of surrounding whitespace; an empty name or a
    missing operator is a :class:`PredicateError`.
    """
    for op in _OPERATORS:
        idx = clause.find(op)
        if idx > 0:
            name = clause[:idx].strip()
            value = clause[idx + len(op):].strip()
            if not name:
                break
            return Predicate(name=name, op=op, value=value)
    raise PredicateError(
        f"invalid --field {clause!r}: expected NAME=VALUE "
        f"(or >=, <=, >, < for numeric compares)"
    )


def _as_number(text: str) -> Optional[float]:
    """Best-effort numeric parse (int or float), else ``None``.

    Accepts ``0x``-prefixed hex too, so ``--field method>=0x08`` works.
    """
    try:
        if text.lower().startswith(("0x", "-0x", "+0x")):
            return float(int(text, 16))
        return float(text)
    except (ValueError, TypeError):
        return None


def _values_for(field: DecodedField) -> Tuple[List[str], Optional[float]]:
    """Return a field's comparable string forms and its numeric value (if any).

    The string forms include the raw value and any enum label, both lowercased,
    so ``=`` matching can succeed against how the user naturally names things
    (``method=deflate`` or ``method=8``). The numeric value (when the field is
    numeric) drives the ordered comparisons.
    """
    strings: List[str] = [str(field.value).lower()]
    if field.label is not None:
        strings.append(str(field.label).lower())
    number = field.value if isinstance(field.value, (int, float)) else None
    return strings, (float(number) if number is not None else None)


def _field_satisfies(field: DecodedField, pred: Predicate) -> bool:
    """True when a single decoded ``field`` satisfies ``pred``."""
    strings, number = _values_for(field)

    if pred.op == "=":
        want = pred.value.lower()
        if want in strings:
            return True
        # Numeric equality tolerant of formatting (e.g. "1920" vs 1920.0).
        want_num = _as_number(pred.value)
        return want_num is not None and number is not None and number == want_num

    # Ordered comparisons are numeric-only; a non-numeric field never matches.
    want_num = _as_number(pred.value)
    if want_num is None or number is None:
        return False
    if pred.op == ">=":
        return number >= want_num
    if pred.op == "<=":
        return number <= want_num
    if pred.op == ">":
        return number > want_num
    if pred.op == "<":
        return number < want_num
    return False  # pragma: no cover - operator set is closed


def _matching_fields(
    decoded: Sequence[DecodedField], pred: Predicate
) -> List[DecodedField]:
    """All decoded fields whose name matches ``pred`` *and* satisfy it."""
    name = pred.name.lower()
    return [
        f for f in decoded if f.name.lower() == name and _field_satisfies(f, pred)
    ]


@dataclass(frozen=True)
class FileMatch:
    """A file that satisfied every predicate, with the fields that matched."""

    path: str
    format: str
    matched: Tuple[DecodedField, ...]

    def summary(self) -> str:
        """One-line ``path: format (field=value, …)`` summary."""
        parts = ", ".join(f"{f.name}={f.display()}" for f in self.matched)
        return f"{self.path}: {self.format} ({parts})"


def _read_head(path: str, size: int = HEAD_SIZE) -> Optional[bytes]:
    """Read a file's head, or ``None`` when it can't be read (skipped)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except (OSError, ValueError):
        return None


def evaluate_file(
    path: str, predicates: Sequence[Predicate], *, head: Optional[bytes] = None
) -> Optional[FileMatch]:
    """Evaluate one file against ``predicates``; return a match or ``None``.

    A file matches only when *every* predicate is satisfied by at least one
    decoded header field. ``head`` may be supplied to avoid a disk read (used by
    tests); otherwise it is read from ``path``.
    """
    if head is None:
        head = _read_head(path)
    if head is None:
        return None

    matches = identify(head)
    if not matches:
        return None
    best = matches[0]
    decoded = decoded_fields_for(best.name, head)
    if not decoded:
        return None

    hits: List[DecodedField] = []
    for pred in predicates:
        found = _matching_fields(decoded, pred)
        if not found:
            return None  # AND semantics: any unmet predicate disqualifies
        hits.extend(found)

    return FileMatch(path=path, format=best.name, matched=tuple(hits))


def find_matches(
    paths: Iterable[str], predicates: Sequence[Predicate]
) -> List[FileMatch]:
    """Evaluate every path, returning the files that satisfy all predicates."""
    out: List[FileMatch] = []
    for path in paths:
        match = evaluate_file(path, predicates)
        if match is not None:
            out.append(match)
    return out


def find_result_dict(
    matches: Sequence[FileMatch], predicates: Sequence[Predicate]
) -> dict:
    """Build the ``--json`` payload for a ``find`` run (schema-versioned)."""
    from .render import SCHEMA_VERSION  # local import avoids a cycle at import time

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "bytebite",
        "action": "find",
        "query": [p.describe() for p in predicates],
        "count": len(matches),
        "matches": [
            {
                "path": m.path,
                "format": m.format,
                "fields": [
                    {
                        "name": f.name,
                        "value": f.value,
                        "label": f.label,
                    }
                    for f in m.matched
                ],
            }
            for m in matches
        ],
    }
