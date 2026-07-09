"""``bytebite explain <format>`` — the pocket reference (issue #7).

Milestones 2–6 answered questions *about a file you have*: identify it, peek at
its annotated header. ``explain`` inverts that: it prints a known format's
**header layout / spec without needing a file at all**, turning bytebite into a
quick "what does this header look like again?" reference.

It is a thin, read-only view over data bytebite already carries:

* the :mod:`bytebite.signatures` registry gives the magic bytes, offset, mask,
  category and one-line description;
* the :mod:`bytebite.fields` layouts give the documented per-field breakdown for
  the formats that have one (PNG, ELF, ZIP, WAV — the M6 set).

Nothing here reads the filesystem or executes anything; it just formats the
static reference data. ``--json`` emits the same content as one stable line so
the reference is scriptable too (e.g. building docs or shell completions).

Format resolution is forgiving on purpose: users type ``png``, ``PNG``,
``PNG image`` or ``.wav`` and get the right entry. When a token is ambiguous or
unknown we say so and (for unknown) suggest the closest known names, mirroring
the friendly tone of the identify path.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .fields import Field, fields_for, has_field_detail
from .render import SCHEMA_VERSION, format_hex, to_json
from .signatures import Signature, all_signatures

# ``explain`` renders the ELF layout too, but the ELF field table is
# endianness-dependent (see :func:`bytebite.fields._elf_fields`). With no file
# in hand we present the little-endian view — by far the common case (x86-64,
# AArch64, RISC-V little) — and label it so the reference stays honest. A single
# ``EI_DATA = little`` byte at offset 5 is enough to steer the builder.
_ELF_LE_PROBE = b"\x7fELF\x01\x01"


@dataclass(frozen=True)
class FormatInfo:
    """Everything ``explain`` shows about one format, gathered from the registry.

    ``signatures`` are all the registry entries that share the resolved format
    ``name`` (some formats have several, e.g. the two GIF versions or the two
    MP3 framings); the first is treated as canonical for the headline.
    ``fields`` is the documented header layout (empty when the format has none).
    """

    name: str
    category: str
    signatures: Tuple[Signature, ...]
    fields: Tuple[Field, ...]

    @property
    def canonical(self) -> Signature:
        return self.signatures[0]

    @property
    def has_fields(self) -> bool:
        return bool(self.fields)


def _canonical_names() -> List[str]:
    """All distinct format names in registry order (de-duplicated, stable)."""
    seen: Dict[str, None] = {}
    for sig in all_signatures():
        seen.setdefault(sig.name, None)
    return list(seen.keys())


def _normalise(token: str) -> str:
    """Lower-case and strip noise so ``.PNG`` / ``png`` / ``PNG image`` unify.

    We drop a leading dot (so a file *extension* works), collapse whitespace,
    and lower-case. The trailing format *kind* word (``image``/``archive``/
    ``document``/``executable``/``audio``/``database``) is not stripped here so
    an exact full name like ``"zip archive"`` still matches directly; the token
    matcher below also tries a magic-word-only comparison.
    """
    return token.strip().lstrip(".").strip().lower()


def _name_tokens(name: str) -> List[str]:
    """Search keys for a format ``name`` (full, and first word).

    ``"PNG image"`` yields ``["png image", "png"]`` so both ``png`` and the full
    name resolve. The first word is the mnemonic people actually type.
    """
    low = name.lower()
    keys = [low]
    first = low.split(" ", 1)[0]
    if first != low:
        keys.append(first)
    return keys


def resolve_format(token: str) -> Tuple[Optional[str], List[str]]:
    """Resolve a user ``token`` to a canonical format name.

    Returns ``(name, candidates)``:

    * exact/unique hit → ``(name, [name])``;
    * ambiguous (a bare mnemonic shared by >1 name) → ``(None, [matches…])``;
    * miss → ``(None, close_suggestions)`` (possibly empty).

    Matching is case-insensitive, extension-friendly (``.wav``) and accepts
    either the full name (``"wav audio"``) or the leading mnemonic (``wav``).
    """
    want = _normalise(token)
    names = _canonical_names()

    # 1) Exact match on a full name wins outright.
    full = [n for n in names if want == n.lower()]
    if len(full) == 1:
        return full[0], full

    # 2) Mnemonic (leading-word) match. Several names can share a mnemonic
    # (``zip`` → "ZIP archive" and "ZIP archive (empty)"); prefer the shortest
    # name as the canonical one, which is the plain, unqualified format. Only
    # treat it as ambiguous when two mnemonic hits are the *same* length (a
    # genuine tie with no obvious primary).
    mnemonic = [n for n in names if want and want == n.lower().split(" ", 1)[0]]
    if len(mnemonic) == 1:
        return mnemonic[0], mnemonic
    if len(mnemonic) > 1:
        mnemonic.sort(key=lambda n: (len(n), n))
        if len(mnemonic[0]) < len(mnemonic[1]):
            return mnemonic[0], [mnemonic[0]]
        return None, mnemonic

    # 3) Substring fallback ("sqlite" → "SQLite database"): unambiguous only.
    contains = [n for n in names if want and want in n.lower()]
    if len(contains) == 1:
        return contains[0], contains
    if len(contains) > 1:
        return None, contains

    # 3) Miss: offer the closest known names as a hint. We match against both
    # full names and their leading mnemonics (so a typo like ``pgn`` still
    # suggests ``png``), then map any hit back to its canonical spelling.
    lower_to_name = {n.lower(): n for n in names}
    mnemonic_to_name: Dict[str, str] = {}
    for n in names:
        for key in _name_tokens(n):
            mnemonic_to_name.setdefault(key, n)
    pool = list(mnemonic_to_name.keys())
    close = get_close_matches(want, pool, n=5, cutoff=0.5)
    # De-duplicate suggested canonical names while preserving match order.
    suggestions: List[str] = []
    for key in close:
        name = mnemonic_to_name.get(key) or lower_to_name.get(key)
        if name and name not in suggestions:
            suggestions.append(name)
        if len(suggestions) >= 3:
            break
    return None, suggestions


def format_info(name: str) -> FormatInfo:
    """Gather the reference data for an already-resolved canonical ``name``."""
    sigs = tuple(s for s in all_signatures() if s.name == name)
    if not sigs:  # pragma: no cover - callers resolve first
        raise KeyError(name)
    layout = fields_for(name, _ELF_LE_PROBE) if has_field_detail(name) else ()
    return FormatInfo(
        name=name,
        category=sigs[0].category,
        signatures=sigs,
        fields=layout,
    )


def _magic_repr(sig: Signature) -> str:
    """Readable magic for a signature, wildcards shown as ``??`` under a mask."""
    if sig.mask is None:
        return format_hex(sig.magic)
    # Render masked (wildcard) bytes as ``??`` and fixed bytes literally so the
    # variable parts of a family magic (JPEG's marker byte, WAV's size) are
    # obvious in the reference.
    out: List[str] = []
    for i, b in enumerate(sig.magic):
        m = sig.mask[i]
        if m == 0x00:
            out.append("??")
        elif m != 0xFF:
            out.append(f"~{b:02x}")  # partially-masked byte
        elif 0x20 <= b <= 0x7E and b != 0x5C:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def _field_dict(fld: Field) -> Dict[str, Any]:
    """JSON view of one documented field (no bytes — this is a spec, not a file)."""
    d: Dict[str, Any] = {
        "name": fld.name,
        "offset": fld.offset,
        "size": fld.size,
        "type": fld.type,
    }
    if fld.note:
        d["note"] = fld.note
    if fld.enum is not None:
        # Stringify keys so the JSON is valid regardless of int/hex raw codes.
        d["enum"] = {str(k): v for k, v in fld.enum.items()}
    return d


def explain_dict(info: FormatInfo) -> Dict[str, Any]:
    """Build the ``--json`` payload for ``explain`` (schema-versioned).

    Schema::

        {
          "schema_version": 1,
          "tool": "bytebite",
          "format": {
            "name": str, "category": str,
            "description": str,
            "signatures": [ {"magic": str, "offset": int, "masked": bool} ],
            "fields": [ {"name","offset","size","type", "note"?, "enum"?} ]
          }
        }
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "bytebite",
        "format": {
            "name": info.name,
            "category": info.category,
            "description": info.canonical.description,
            "signatures": [
                {
                    "magic": _magic_repr(s),
                    "offset": s.offset,
                    "masked": s.mask is not None,
                }
                for s in info.signatures
            ],
            "fields": [_field_dict(f) for f in info.fields],
        },
    }


def render_explain(info: FormatInfo) -> str:
    """Human-readable reference block for a resolved format.

    Shows the headline (name/category/description), each magic-byte fingerprint
    with its offset, and — when available — the documented header field layout
    as an aligned table (offset range, size, type, name, note). Enum-valued
    fields list their known codes so the reference is self-contained.
    """
    canonical = info.canonical
    lines: List[str] = [
        f"📖 {info.name}  (category: {info.category})",
    ]
    if canonical.description:
        lines.append(f"   {canonical.description}")

    # Magic fingerprints. Most formats have one; a few carry a small family.
    lines.append("")
    if len(info.signatures) == 1:
        lines.append("Magic:")
    else:
        lines.append(f"Magic ({len(info.signatures)} signatures):")
    for sig in info.signatures:
        rng = f"offset 0x{sig.offset:02x}"
        wildcard = "  (?? = wildcard)" if sig.mask is not None else ""
        lines.append(f"   {_magic_repr(sig)}   @ {rng}{wildcard}")

    # Documented header fields (the whole point of `explain`).
    lines.append("")
    if not info.fields:
        lines.append(
            "Header fields: none documented yet "
            "(only magic-byte identification for this format)."
        )
        return "\n".join(lines)

    if info.name == "ELF executable":
        lines.append("Header fields (little-endian view; big-endian swaps 16-bit ints):")
    else:
        lines.append("Header fields:")

    # Aligned columns: offset range | size | type | name | note.
    rows: List[Tuple[str, str, str, str, str]] = []
    for fld in info.fields:
        if fld.size > 1:
            span = f"0x{fld.offset:02x}–0x{fld.end - 1:02x}"
        else:
            span = f"0x{fld.offset:02x}"
        rows.append((span, str(fld.size), fld.type, fld.name, fld.note))

    off_w = max(len(r[0]) for r in rows)
    sz_w = max(len(r[1]) for r in rows)
    ty_w = max(len(r[2]) for r in rows)
    nm_w = max(len(r[3]) for r in rows)
    for span, size, ty, nm, note in rows:
        note_part = f"  — {note}" if note else ""
        lines.append(
            f"   {span:<{off_w}}  {size:>{sz_w}}B  {ty:<{ty_w}}  "
            f"{nm:<{nm_w}}{note_part}".rstrip()
        )

    # Enumerated fields: spell out the known codes so nothing is left implicit.
    enum_fields = [f for f in info.fields if f.enum]
    if enum_fields:
        lines.append("")
        lines.append("Known values:")
        for fld in enum_fields:
            coded = ", ".join(
                f"{_enum_key(k)}={v}" for k, v in fld.enum.items()
            )
            lines.append(f"   {fld.name}: {coded}")

    return "\n".join(lines)


def _enum_key(key: Any) -> str:
    """Render an enum key: small ints plainly, larger/flag-like ones as hex."""
    if isinstance(key, int) and key > 9:
        return f"0x{key:02x}"
    return str(key)


def explain(token: str) -> Tuple[Optional[FormatInfo], List[str], str]:
    """Resolve ``token`` and gather its reference info.

    Returns ``(info, candidates, status)``:

    * ``status == "ok"`` → ``info`` is populated; ``candidates`` is ``[name]``.
    * ``status == "ambiguous"`` → ``info`` is ``None``; ``candidates`` lists the
      matching format names to disambiguate between.
    * ``status == "unknown"`` → ``info`` is ``None``; ``candidates`` holds close
      spelling suggestions (possibly empty).

    The tri-state lets the CLI phrase "did you mean X or Y?" (ambiguous) versus
    "unknown format, did you mean X?" (typo) versus a bare "unknown" correctly.
    """
    want = _normalise(token)
    names = _canonical_names()
    # An exact/substring resolution means the token *did* name something; only a
    # true miss should read as "unknown". Reuse resolve_format's logic and infer
    # the status from whether the token matched any name at all.
    name, candidates = resolve_format(token)
    if name is not None:
        return format_info(name), candidates, "ok"
    matched_any = any(want in _name_tokens(n) for n in names) or any(
        want and want in n.lower() for n in names
    )
    status = "ambiguous" if matched_any else "unknown"
    return None, candidates, status


def known_formats() -> Sequence[str]:
    """Public helper: the canonical format names ``explain`` understands."""
    return tuple(_canonical_names())
