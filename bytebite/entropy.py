"""Per-region Shannon-entropy strip (issue #21).

``bytebite entropy <file>`` slices a blob into fixed-size blocks (default 256B)
and reports the Shannon entropy (0.0-8.0 bits/byte) of each block, so a user can
glance at a file and spot compressed/encrypted regions (high entropy) versus
text, padding and headers (low entropy) without opening a full RE tool.

The maths is pure stdlib: entropy of a block is
``-sum(p * log2(p) for each present byte value)`` where ``p`` is that value's
frequency in the block. A block of one repeated byte scores ``0.0``; a uniform
mix of all 256 values approaches ``8.0``.

Rendering mirrors the rest of bytebite: an ANSI bar on real terminals, plain
aligned text when colour is off (``NO_COLOR``/non-TTY/``--json``), and a stable
schema-versioned ``--json`` line.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional

from .render import SCHEMA_VERSION, color_enabled

TOOL = "bytebite"
DEFAULT_BLOCK = 256
MAX_BITS = 8.0

# Heuristic verdict thresholds (bits/byte over the whole blob).
_HIGH_ENTROPY = 7.5  # compressed/encrypted territory
_LOW_ENTROPY = 5.0  # text/structured territory

# Bar rendering.
_BAR_WIDTH = 32
# A green->yellow->red ramp so high-entropy blocks jump out.
_ANSI_RESET = "\x1b[0m"


def shannon_entropy(data: bytes) -> float:
    """Return the Shannon entropy of ``data`` in bits/byte (0.0-8.0).

    An empty block has no information and scores ``0.0``.
    """
    if not data:
        return 0.0
    n = len(data)
    entropy = 0.0
    for count in Counter(data).values():
        p = count / n
        entropy -= p * math.log2(p)
    return entropy


@dataclass(frozen=True)
class Block:
    """One block's entropy over a half-open byte range ``[offset, end)``."""

    offset: int
    end: int
    entropy: float


@dataclass(frozen=True)
class EntropyReport:
    """The full per-block entropy scan of a blob."""

    source: str
    block_size: int
    blocks: List[Block]
    overall: float
    verdict: str


def _verdict(overall: float) -> str:
    """Map an overall entropy value to a short human verdict."""
    if overall >= _HIGH_ENTROPY:
        return "looks compressed/encrypted"
    if overall <= _LOW_ENTROPY:
        return "mostly text/structured"
    return "mixed"


def scan_entropy(
    data: bytes, *, block_size: int = DEFAULT_BLOCK, source: str = "<stdin>"
) -> EntropyReport:
    """Slice ``data`` into ``block_size`` chunks and score each one.

    The final block may be short; its entropy is computed over its actual
    length. ``overall`` is the entropy of the whole blob (not an average of the
    per-block values, which would be misleading for uneven data).
    """
    if block_size < 1:
        raise ValueError("block size must be >= 1")

    blocks: List[Block] = []
    for offset in range(0, len(data), block_size):
        chunk = data[offset : offset + block_size]
        blocks.append(
            Block(offset=offset, end=offset + len(chunk), entropy=shannon_entropy(chunk))
        )

    overall = shannon_entropy(data)
    return EntropyReport(
        source=source,
        block_size=block_size,
        blocks=blocks,
        overall=overall,
        verdict=_verdict(overall),
    )


def entropy_result_dict(report: EntropyReport) -> dict:
    """Build the stable ``--json`` payload for an :class:`EntropyReport`."""
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "source": report.source,
        "block_size": report.block_size,
        "blocks": [
            {"offset": b.offset, "end": b.end, "entropy": round(b.entropy, 4)}
            for b in report.blocks
        ],
        "overall": round(report.overall, 4),
        "verdict": report.verdict,
    }


def _bar_color(entropy: float) -> str:
    """ANSI colour for an entropy value: green (low) -> yellow -> red (high)."""
    if entropy >= _HIGH_ENTROPY:
        return "\x1b[31m"  # red
    if entropy >= _LOW_ENTROPY:
        return "\x1b[33m"  # yellow
    return "\x1b[32m"  # green


def _bar(entropy: float, *, use_color: bool) -> str:
    """Render a fixed-width bar for ``entropy`` (0.0-8.0)."""
    filled = int(round((entropy / MAX_BITS) * _BAR_WIDTH))
    filled = max(0, min(_BAR_WIDTH, filled))
    body = "█" * filled + "·" * (_BAR_WIDTH - filled)
    if use_color:
        return f"{_bar_color(entropy)}{body}{_ANSI_RESET}"
    return body


def render_entropy(report: EntropyReport, *, use_color: Optional[bool] = None) -> str:
    """Render ``report`` as an aligned per-block strip plus a summary line.

    ``use_color`` overrides TTY/``NO_COLOR`` auto-detection when given (tests
    pass ``False`` for stable output).
    """
    enabled = color_enabled() if use_color is None else use_color

    lines: List[str] = []
    if report.blocks:
        end_w = max(len(f"{b.end:x}") for b in report.blocks)
        off_w = max(len(f"{b.offset:x}") for b in report.blocks)
    else:
        end_w = off_w = 1

    for b in report.blocks:
        rng = f"{b.offset:0{off_w}x}-{b.end:0{end_w}x}"
        bar = _bar(b.entropy, use_color=enabled)
        lines.append(f"  {rng}  {b.entropy:4.2f}  {bar}")

    header = (
        f"{TOOL} entropy: {report.source} "
        f"(block {report.block_size}B, {len(report.blocks)} blocks)"
    )
    summary = f"overall {report.overall:.2f} bits/byte — {report.verdict}"
    return "\n".join([header, *lines, "", summary])
