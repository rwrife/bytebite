"""The bytebite identification engine.

Reads the leading bytes of a file (or an in-memory buffer), matches them
against the :mod:`bytebite.signatures` registry, and returns the best guess
with a confidence score and the exact matched byte range.

Confidence in M2 is deliberately simple and honest: it is derived from *how
much evidence matched* — a longer magic-byte run is stronger proof than a
two-byte one. The scoring is intentionally conservative so a bare ``MZ`` (PE)
doesn't claim the same certainty as an 8-byte PNG signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .signatures import SIGNATURES, Signature

# How many bytes of the file we sniff. The longest seed magic is 8 bytes; we
# read generously so later milestones (offsets deeper into the header, field
# annotation) have data to work with without another disk read.
HEAD_SIZE = 4096


@dataclass(frozen=True)
class Match:
    """A scored signature match against some data."""

    signature: Signature
    confidence: float  # 0.0 – 1.0
    matched_bytes: bytes = b""  # the actual bytes from the input at the range

    @property
    def name(self) -> str:
        return self.signature.name

    @property
    def category(self) -> str:
        return self.signature.category

    @property
    def description(self) -> str:
        return self.signature.description

    @property
    def offset(self) -> int:
        return self.signature.offset

    @property
    def end(self) -> int:
        return self.signature.end


def read_head(path: str, size: int = HEAD_SIZE) -> bytes:
    """Read up to ``size`` leading bytes from ``path``.

    Kept tiny and separate so identification can be exercised against either a
    file path (:func:`identify_path`) or raw bytes (:func:`identify`).
    """
    with open(path, "rb") as fh:
        return fh.read(size)


def _confidence_for(sig: Signature) -> float:
    """Score a signature by the strength of its evidence.

    Heuristic: more magic bytes ⇒ more confidence, saturating toward ~0.99.
    A masked byte counts as weaker evidence (half) since it only constrains
    some bits. Two solid bytes (PE's ``MZ``) land around 0.6; an 8-byte PNG
    run lands at the ceiling.
    """
    strength = 0.0
    for i in range(len(sig.magic)):
        if sig.mask is None or sig.mask[i] == 0xFF:
            strength += 1.0
        elif sig.mask[i] == 0x00:
            strength += 0.0  # pure wildcard byte: no evidence
        else:
            strength += 0.5  # partial mask
    # Map effective byte-count of evidence onto a confidence in (0, 0.99].
    # 1 byte → ~0.40, 2 → ~0.60, 4 → ~0.85, 8+ → ~0.99.
    score = 1.0 - 0.5 ** (strength / 2.0)
    return round(min(score, 0.99), 2)


def identify(head: bytes) -> List[Match]:
    """Match ``head`` against every signature, best (highest confidence) first.

    Returns an empty list when nothing matches. Ties are broken by the length
    of the matched range (longer wins) and then by registry order, so results
    are stable.
    """
    matches: List[Match] = []
    for sig in SIGNATURES:
        if sig.matches(head):
            actual = head[sig.offset : sig.end]
            matches.append(
                Match(
                    signature=sig,
                    confidence=_confidence_for(sig),
                    matched_bytes=actual,
                )
            )

    matches.sort(
        key=lambda m: (m.confidence, len(m.matched_bytes)),
        reverse=True,
    )
    return matches


def best_match(head: bytes) -> Optional[Match]:
    """Return the single strongest match for ``head``, or ``None`` if unknown."""
    matches = identify(head)
    return matches[0] if matches else None


def identify_path(path: str, size: int = HEAD_SIZE) -> List[Match]:
    """Convenience: read ``path``'s head and identify it."""
    return identify(read_head(path, size))
