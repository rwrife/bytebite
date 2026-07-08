"""Field-level header decoding — M6.

Milestones 2–5 answered *"what is this file, and where do its magic bytes
sit?"*. M6 goes one field deeper: for a handful of well-known formats we decode
and label the **individual header fields** so ``bytebite peek`` shows you the
PNG image's width/height, the ELF class/machine, the ZIP compression method, or
the WAV sample rate — not just the magic range.

Design
------
* **Declarative, like signatures.** A :class:`Field` is plain data: a name, an
  absolute byte offset, a size, and a *type* string naming how to interpret the
  bytes (``u16be``, ``u32le``, ``ascii`` …). Adding a field is a data edit, not
  a code change — the same extensibility story as :mod:`bytebite.signatures`.
* **A tiny decoder table.** :data:`_DECODERS` maps each type string to a pure
  function ``bytes -> object``. Endianness and signedness live in the type name
  so the layout tables stay readable (``("width", 16, 4, "u32be")``).
* **Optional enum labels.** A field may carry an ``enum`` mapping so a raw code
  is rendered as a human name (ELF class ``2`` → ``64-bit``) while the JSON
  payload keeps both the raw value and the label.
* **Layouts attach by signature name.** :func:`fields_for` looks a format up by
  its signature ``name`` in :data:`FIELD_LAYOUTS`. Keeping the mapping here (not
  inside :mod:`bytebite.signatures`) keeps the signature registry a pure,
  dependency-free data module while still letting a :class:`~bytebite.signatures.Signature`
  expose an optional ``fields`` tuple.

Only formats we can decode *safely from the header alone* are included; we never
seek deep into the file or execute anything (see PLAN.md "out of scope").
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field as _dc_field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# --- Field model ------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """One labelled span inside a header, with a rule for decoding its bytes.

    Attributes
    ----------
    name:
        Human label shown in ``peek`` and used as the JSON key, e.g. ``"width"``.
    offset:
        Absolute byte offset of the field within the file/head.
    size:
        Field length in bytes.
    type:
        Decoder key (see :data:`_DECODERS`): ``u8``, ``u16be``/``u16le``,
        ``u32be``/``u32le``, ``ascii``, ``hex``, ``magic`` (raw, shown as hex).
    enum:
        Optional ``{raw_value: label}`` map. When the decoded value is a key,
        ``peek`` shows the label and the JSON payload adds a ``label`` field.
    note:
        Optional short human note appended to the field's caption line.
    """

    name: str
    offset: int
    size: int
    type: str
    enum: Optional[Mapping[Any, str]] = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError(f"field {self.name!r} has non-positive size {self.size}")
        if self.offset < 0:
            raise ValueError(f"field {self.name!r} has negative offset")
        if self.type not in _DECODERS:
            raise ValueError(f"field {self.name!r} has unknown type {self.type!r}")

    @property
    def end(self) -> int:
        """Offset just past the field (``offset + size``)."""
        return self.offset + self.size


# --- Decoders ---------------------------------------------------------------
#
# Each decoder turns the exact field bytes into a Python value. They are total
# on correctly-sized input; :func:`decode_field` guarantees the slice length
# before calling, so decoders don't need to re-check.


def _u8(b: bytes) -> int:
    return b[0]


def _u16be(b: bytes) -> int:
    return struct.unpack(">H", b)[0]


def _u16le(b: bytes) -> int:
    return struct.unpack("<H", b)[0]


def _u32be(b: bytes) -> int:
    return struct.unpack(">I", b)[0]


def _u32le(b: bytes) -> int:
    return struct.unpack("<I", b)[0]


def _ascii(b: bytes) -> str:
    # Printable ASCII rendered literally; other bytes shown as dots so the value
    # stays a clean, single-line string (matches the ASCII column in the dump).
    return "".join(chr(c) if 0x20 <= c <= 0x7E else "." for c in b)


def _hex(b: bytes) -> str:
    return b.hex()


_DECODERS: Dict[str, Callable[[bytes], Any]] = {
    "u8": _u8,
    "u16be": _u16be,
    "u16le": _u16le,
    "u32be": _u32be,
    "u32le": _u32le,
    "ascii": _ascii,
    "hex": _hex,
    "magic": _hex,  # alias: a raw magic/identifier span shown as hex
}


@dataclass(frozen=True)
class DecodedField:
    """A :class:`Field` resolved against real bytes.

    ``value`` is the decoded Python value; ``label`` is the enum label when one
    applies (else ``None``); ``raw`` is the exact bytes of the field.
    """

    field: Field
    value: Any
    raw: bytes
    label: Optional[str] = None

    @property
    def name(self) -> str:
        return self.field.name

    @property
    def offset(self) -> int:
        return self.field.offset

    @property
    def end(self) -> int:
        return self.field.end

    @property
    def note(self) -> str:
        return self.field.note

    def display(self) -> str:
        """Human rendering of the value: label (raw) when an enum matched."""
        if self.label is not None:
            return f"{self.label} ({self.value})"
        return str(self.value)


def decode_field(fld: Field, data: bytes) -> Optional[DecodedField]:
    """Decode ``fld`` from ``data`` (the file head).

    Returns ``None`` when ``data`` is too short to contain the whole field, so a
    truncated header degrades gracefully to "just the fields we can prove".
    """
    if len(data) < fld.end:
        return None
    raw = data[fld.offset : fld.end]
    value = _DECODERS[fld.type](raw)
    label = None
    if fld.enum is not None and value in fld.enum:
        label = fld.enum[value]
    return DecodedField(field=fld, value=value, raw=raw, label=label)


def decode_fields(fields: Sequence[Field], data: bytes) -> List[DecodedField]:
    """Decode each field that fits in ``data``; skip any that overrun it."""
    out: List[DecodedField] = []
    for fld in fields:
        decoded = decode_field(fld, data)
        if decoded is not None:
            out.append(decoded)
    return out


# --- Per-format field layouts ----------------------------------------------
#
# Absolute offsets, decoded straight from the header. Sources: the respective
# format specs (PNG IHDR, ELF Ehdr, ZIP local file header, WAV fmt chunk). Only
# the genuinely interesting header fields are annotated — not every byte.

# PNG: the 8-byte signature is followed by the IHDR chunk. Layout after magic:
#   [4] length  [4] "IHDR"  [4] width  [4] height  [1] bit depth
#   [1] colour type  [1] compression  [1] filter  [1] interlace   (all BE)
_PNG_COLOR_TYPES = {
    0: "grayscale",
    2: "truecolour (RGB)",
    3: "indexed",
    4: "grayscale+alpha",
    6: "truecolour+alpha (RGBA)",
}
PNG_FIELDS: Tuple[Field, ...] = (
    Field("IHDR length", 8, 4, "u32be", note="chunk length (13)"),
    Field("chunk type", 12, 4, "ascii", note="always 'IHDR'"),
    Field("width", 16, 4, "u32be", note="pixels"),
    Field("height", 20, 4, "u32be", note="pixels"),
    Field("bit depth", 24, 1, "u8"),
    Field("colour type", 25, 1, "u8", enum=_PNG_COLOR_TYPES),
    Field("compression", 26, 1, "u8", enum={0: "deflate"}),
    Field("filter", 27, 1, "u8", enum={0: "adaptive"}),
    Field("interlace", 28, 1, "u8", enum={0: "none", 1: "Adam7"}),
)

# ELF: the identification bytes then a few header fields. We stay in the
# endian-independent e_ident block plus the (endian-tagged) type/machine, which
# we read big- or little-endian per EI_DATA. To keep the table declarative we
# annotate the e_ident fields here; type/machine are added dynamically below in
# :func:`_elf_fields` because their endianness depends on byte 5.
_ELF_CLASS = {1: "32-bit", 2: "64-bit"}
_ELF_DATA = {1: "little-endian", 2: "big-endian"}
_ELF_OSABI = {0: "System V", 3: "Linux", 9: "FreeBSD", 6: "Solaris"}
_ELF_TYPE = {1: "relocatable", 2: "executable", 3: "shared object", 4: "core"}
_ELF_MACHINE = {
    0x02: "SPARC",
    0x03: "x86",
    0x08: "MIPS",
    0x14: "PowerPC",
    0x28: "ARM",
    0x3E: "x86-64",
    0xB7: "AArch64",
    0xF3: "RISC-V",
}
_ELF_IDENT_FIELDS: Tuple[Field, ...] = (
    Field("EI_MAG", 0, 4, "magic", note="0x7F 'ELF'"),
    Field("class", 4, 1, "u8", enum=_ELF_CLASS),
    Field("data", 5, 1, "u8", enum=_ELF_DATA),
    Field("version", 6, 1, "u8", enum={1: "current"}),
    Field("OS ABI", 7, 1, "u8", enum=_ELF_OSABI),
)

# ZIP local file header (offset 0): signature, version, flags, method, time,
# date, CRC-32, sizes, name/extra lengths. We annotate the compact, universally
# present fixed fields (methods enum covers the common ones).
_ZIP_METHOD = {0: "stored", 8: "deflate", 12: "bzip2", 14: "LZMA", 93: "zstd"}
ZIP_FIELDS: Tuple[Field, ...] = (
    Field("signature", 0, 4, "magic", note="PK\\x03\\x04"),
    Field("version needed", 4, 2, "u16le", note="min unzip version ×10"),
    Field("flags", 6, 2, "u16le"),
    Field("method", 8, 2, "u16le", enum=_ZIP_METHOD),
    Field("mod time", 10, 2, "u16le", note="MS-DOS time"),
    Field("mod date", 12, 2, "u16le", note="MS-DOS date"),
    Field("CRC-32", 14, 4, "hex"),
    Field("compressed size", 18, 4, "u32le", note="bytes"),
    Field("uncompressed size", 22, 4, "u32le", note="bytes"),
    Field("name length", 26, 2, "u16le"),
    Field("extra length", 28, 2, "u16le"),
)

# WAV: RIFF header then the "fmt " chunk. For canonical PCM WAVs the fmt chunk
# begins at offset 12. Layout: "fmt " [4], chunk size [4 LE], audio format
# [2 LE], channels [2 LE], sample rate [4 LE], byte rate [4 LE], block align
# [2 LE], bits/sample [2 LE].
_WAV_FORMAT = {1: "PCM", 3: "IEEE float", 6: "A-law", 7: "µ-law", 0xFFFE: "extensible"}
WAV_FIELDS: Tuple[Field, ...] = (
    Field("RIFF", 0, 4, "ascii", note="container tag"),
    Field("file size", 4, 4, "u32le", note="bytes - 8"),
    Field("WAVE", 8, 4, "ascii", note="form type"),
    Field("fmt chunk", 12, 4, "ascii", note="'fmt '"),
    Field("fmt size", 16, 4, "u32le", note="16 for PCM"),
    Field("audio format", 20, 2, "u16le", enum=_WAV_FORMAT),
    Field("channels", 22, 2, "u16le"),
    Field("sample rate", 24, 4, "u32le", note="Hz"),
    Field("byte rate", 28, 4, "u32le", note="bytes/s"),
    Field("block align", 32, 2, "u16le", note="bytes/frame"),
    Field("bits/sample", 34, 2, "u16le"),
)


def _elf_fields(data: bytes) -> Tuple[Field, ...]:
    """Build the ELF field list, choosing endianness from EI_DATA (byte 5).

    The e_ident block is endian-independent; ``e_type`` (offset 16) and
    ``e_machine`` (offset 18) are 16-bit values whose byte order follows
    EI_DATA. We read that one byte to pick the right decoder so the labels are
    correct on both little- and big-endian binaries.
    """
    fields: List[Field] = list(_ELF_IDENT_FIELDS)
    big = len(data) > 5 and data[5] == 2
    u16 = "u16be" if big else "u16le"
    fields.append(Field("type", 16, 2, u16, enum=_ELF_TYPE))
    fields.append(Field("machine", 18, 2, u16, enum=_ELF_MACHINE))
    return tuple(fields)


# Static layouts keyed by signature name. ELF is dynamic (endianness), so it is
# represented by a builder and resolved in :func:`fields_for`.
FIELD_LAYOUTS: Dict[str, Tuple[Field, ...]] = {
    "PNG image": PNG_FIELDS,
    "ZIP archive": ZIP_FIELDS,
    "WAV audio": WAV_FIELDS,
}

_DYNAMIC_LAYOUTS: Dict[str, Callable[[bytes], Tuple[Field, ...]]] = {
    "ELF executable": _elf_fields,
}


def has_field_detail(name: str) -> bool:
    """True when the format named ``name`` has a field-level layout."""
    return name in FIELD_LAYOUTS or name in _DYNAMIC_LAYOUTS


def fields_for(name: str, data: bytes = b"") -> Tuple[Field, ...]:
    """Return the field layout for signature ``name`` (empty tuple if none).

    ``data`` is only needed for formats whose layout depends on the bytes (ELF
    endianness); static layouts ignore it.
    """
    if name in _DYNAMIC_LAYOUTS:
        return _DYNAMIC_LAYOUTS[name](data)
    return FIELD_LAYOUTS.get(name, ())


def decoded_fields_for(name: str, data: bytes) -> List[DecodedField]:
    """Convenience: resolve *and* decode the layout for ``name`` against ``data``."""
    return decode_fields(fields_for(name, data), data)
