"""The bytebite signature registry.

A :class:`Signature` is a small, declarative description of *how to recognise a
file format* by its magic bytes. Signatures live here as plain data so that
adding a new format is a data edit, not a code change — that's the whole
extensibility story from PLAN.md.

M2 seeds the registry with the eight everyday formats called out in the
milestone: PNG, JPEG, GIF, PDF, ZIP, GZIP, ELF and PE. Later milestones grow
this to ~20 (M4) and attach field-level header layouts (M6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class Signature:
    """A single magic-byte fingerprint for a file format.

    Attributes
    ----------
    name:
        Human-friendly format name, e.g. ``"PNG image"``.
    category:
        Broad bucket — ``image``, ``archive``, ``executable``, ``document`` …
    magic:
        The exact bytes we expect to find at ``offset``.
    offset:
        Byte offset where ``magic`` should appear (usually ``0``).
    mask:
        Optional per-byte mask applied before comparison. When present it must
        be the same length as ``magic``; a byte matches when
        ``(data[i] & mask[i]) == (magic[i] & mask[i])``. Use it for formats
        with "wildcard" nibbles (e.g. a version byte that may vary).
    description:
        One-line human description of the format.
    """

    name: str
    category: str
    magic: bytes
    offset: int = 0
    mask: Optional[bytes] = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.magic:
            raise ValueError(f"signature {self.name!r} has empty magic bytes")
        if self.offset < 0:
            raise ValueError(f"signature {self.name!r} has negative offset")
        if self.mask is not None and len(self.mask) != len(self.magic):
            raise ValueError(
                f"signature {self.name!r}: mask length {len(self.mask)} "
                f"!= magic length {len(self.magic)}"
            )

    @property
    def end(self) -> int:
        """The offset just past the matched range (``offset + len(magic)``)."""
        return self.offset + len(self.magic)

    def matches(self, head: bytes) -> bool:
        """Return ``True`` when ``head`` carries this signature's magic bytes.

        ``head`` is the leading slice of the file (see
        :func:`bytebite.identify.read_head`). If it is too short to contain the
        full magic range, the signature simply does not match.
        """
        window = head[self.offset : self.end]
        if len(window) < len(self.magic):
            return False
        if self.mask is None:
            return window == self.magic
        return all(
            (window[i] & self.mask[i]) == (self.magic[i] & self.mask[i])
            for i in range(len(self.magic))
        )


# --- The registry -----------------------------------------------------------
#
# Kept as a module-level list so callers can iterate it directly and tests can
# assert on its contents. Order is "most specific / longest magic first" as a
# gentle tie-breaker, though :func:`bytebite.identify.identify` also scores by
# match length so ordering is not load-bearing.

SIGNATURES: List[Signature] = [
    Signature(
        name="PNG image",
        category="image",
        magic=b"\x89PNG\r\n\x1a\n",
        description="Portable Network Graphics — lossless raster image.",
    ),
    Signature(
        name="GIF image",
        category="image",
        magic=b"GIF89a",
        description="Graphics Interchange Format (89a) — indexed raster / animation.",
    ),
    Signature(
        name="GIF image",
        category="image",
        magic=b"GIF87a",
        description="Graphics Interchange Format (87a) — indexed raster image.",
    ),
    Signature(
        name="JPEG image",
        category="image",
        # SOI marker FF D8 followed by any FF-prefixed marker (E0=JFIF, E1=Exif,
        # DB, EE, …). The third byte is masked so we accept the whole family.
        magic=b"\xff\xd8\xff\x00",
        mask=b"\xff\xff\xff\x00",
        description="JPEG — lossy compressed raster image.",
    ),
    Signature(
        name="PDF document",
        category="document",
        magic=b"%PDF-",
        description="Portable Document Format.",
    ),
    Signature(
        name="ZIP archive",
        category="archive",
        magic=b"PK\x03\x04",
        description="ZIP archive (local file header) — also the basis of jar/docx/apk.",
    ),
    Signature(
        name="ZIP archive (empty)",
        category="archive",
        magic=b"PK\x05\x06",
        description="Empty ZIP archive (end-of-central-directory record).",
    ),
    Signature(
        name="GZIP archive",
        category="archive",
        magic=b"\x1f\x8b\x08",
        description="gzip-compressed stream (DEFLATE).",
    ),
    Signature(
        name="ELF executable",
        category="executable",
        magic=b"\x7fELF",
        description="Executable and Linkable Format — Unix/Linux binary.",
    ),
    Signature(
        name="PE executable",
        category="executable",
        magic=b"MZ",
        description="DOS/PE executable (Windows .exe/.dll — MZ header).",
    ),
]


def all_signatures() -> Sequence[Signature]:
    """Return the registered signatures (read-only view for callers/tests)."""
    return tuple(SIGNATURES)
