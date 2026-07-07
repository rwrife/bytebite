"""Annotated hex peek — the headline feature from PLAN.md.

``bytebite peek <file>`` renders the first N bytes of a file as a classic
offset / hex / ASCII dump, but with the *recognised magic-byte range* picked
out and labelled. Instead of staring at raw bytes you get to *see* the PNG
signature or the ELF magic sitting right there in the header, with a caption
pointing at exactly which bytes proved the identification.

Design notes
------------
* **Pure stdlib, dependency-free.** Colour is opt-in ANSI, auto-disabled when
  stdout is not a TTY or ``NO_COLOR`` is set (shared with :mod:`bytebite.render`
  via :func:`bytebite.render.color_enabled`). Piped output is therefore plain
  and stable — which is what the golden-string tests assert against.
* **The dump is deterministic.** 16 bytes per row, upper-case hex, a mid-line
  gap after 8 bytes, non-printable ASCII shown as ``.``. This is the layout
  everyone already reads (``xxd``/``hexyl``), so it needs no explanation.
* **Highlighting is data-driven.** Any :class:`~bytebite.identify.Match` carries
  an ``offset``/``end`` range; :func:`render_peek` highlights exactly that span.
  Field-level annotation (multiple labelled spans) is M6 — the rendering here is
  written so extending it to N spans later is a small change, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .identify import Match
from .render import SCHEMA_VERSION, color_enabled, format_hex, result_dict

# Layout constants. Kept module-level so tests can reason about them and a
# future ``--width`` option has one obvious place to hook in.
BYTES_PER_ROW = 16
GROUP_SIZE = 8  # extra space after this many bytes, for readability
DEFAULT_BYTES = 64  # how much of the header we show by default

# A tiny, dependency-free ANSI palette (kept in step with render.py's).
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_INVERSE = "\x1b[7m"

# Character used for bytes that fall outside the printable ASCII range in the
# ASCII column, and the caret used to underline the magic range in plain mode.
_NONPRINT = "."
_CARET = "^"


@dataclass(frozen=True)
class Span:
    """A labelled, optionally-coloured byte range ``[start, end)``.

    ``label`` is shown in the caption beneath the dump. Only the magic span is
    produced today; the dataclass exists so M6's field-level annotation can hand
    :func:`render_peek` a list of these without changing its signature.
    """

    start: int
    end: int
    label: str

    def contains(self, index: int) -> bool:
        return self.start <= index < self.end


def _is_printable(byte: int) -> bool:
    """True for bytes we can show literally in the ASCII column (space..~)."""
    return 0x20 <= byte <= 0x7E


def _hex_pair(byte: int) -> str:
    return f"{byte:02x}"


def _spans_for_match(match: Optional[Match]) -> List[Span]:
    """Build the highlight span(s) for ``match`` (just the magic range today)."""
    if match is None:
        return []
    # Clamp defensively: a signature could, in principle, sit past what we show.
    return [Span(match.offset, match.end, f"{match.name} magic")]


def peek_result_dict(
    data: bytes,
    match: Optional[Match] = None,
    *,
    bytes_shown: int = DEFAULT_BYTES,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the machine-readable ``peek --json`` payload.

    Extends the identification payload (:func:`bytebite.render.result_dict`)
    with the dump metadata a scripter needs: how many bytes were shown, the raw
    header as hex, and the labelled highlight spans (start/end/label + the hex
    of each span). The identification block is reused verbatim so ``peek
    --json`` and ``identify --json`` agree on what a match looks like. Shape is
    versioned by :data:`~bytebite.render.SCHEMA_VERSION`.

    Schema (in addition to the identification keys)::

        {
          ... result_dict keys ...,
          "peek": {
            "bytes_shown": int,
            "total_read": int,
            "hex": "<lowercase hex of the shown bytes>",
            "spans": [ {"start": int, "end": int, "label": str, "hex": str} ]
          }
        }
    """
    view = data[: max(bytes_shown, 0)]
    spans = _spans_for_match(match)
    payload = result_dict(match, source=source)
    payload["peek"] = {
        "bytes_shown": len(view),
        "total_read": len(data),
        "hex": view.hex(),
        "spans": [
            {
                "start": s.start,
                "end": s.end,
                "label": s.label,
                "hex": data[s.start : s.end].hex(),
            }
            for s in spans
        ],
    }
    return payload


def _paint(text: str, *codes: str, enabled: bool) -> str:
    if not enabled or not codes:
        return text
    return "".join(codes) + text + _RESET


def _row_offsets(total: int) -> range:
    return range(0, total, BYTES_PER_ROW)


def render_peek(
    data: bytes,
    match: Optional[Match] = None,
    *,
    bytes_shown: int = DEFAULT_BYTES,
    source: str = "<data>",
    use_color: Optional[bool] = None,
) -> str:
    """Return the annotated hex-peek block for ``data``.

    Parameters
    ----------
    data:
        The leading bytes of the file (already truncated by the caller is fine;
        we also clamp to ``bytes_shown`` here so callers can pass a larger head).
    match:
        The identification result whose magic range should be highlighted. When
        ``None`` the dump still renders — just without a highlight — so ``peek``
        is useful even on unknown blobs.
    bytes_shown:
        How many bytes to display (``--bytes N``). Values < 1 render just the
        header lines and an empty dump.
    source:
        Display label for the input (a path, or ``"<stdin>"``).
    use_color:
        Overrides TTY/``NO_COLOR`` auto-detection when given (tests pass False).
    """
    enabled = color_enabled() if use_color is None else use_color
    view = data[: max(bytes_shown, 0)]
    spans = _spans_for_match(match)

    lines: List[str] = []

    # --- Caption / header ---------------------------------------------------
    title = _paint("hex peek", _BOLD, _CYAN, enabled=enabled)
    shown = len(view)
    total_note = "" if shown == len(data) else f" (of ≥{len(data)} read)"
    lines.append(f"🔦 {title} — {source}   showing {shown} byte(s){total_note}")

    if match is not None and shown > match.offset:
        rng = _fmt_range(match.offset, match.end)
        lines.append(
            _paint(
                f"   highlighting {match.name} magic at {rng}",
                _DIM,
                enabled=enabled,
            )
        )

    # --- The dump ------------------------------------------------------------
    for base in _row_offsets(shown):
        row = view[base : base + BYTES_PER_ROW]
        lines.append(_render_row(base, row, spans, enabled=enabled))

    if shown == 0:
        lines.append(_paint("   (no bytes to show)", _DIM, enabled=enabled))

    # --- Caption underline (plain mode gets carets; colour speaks for itself)
    if spans and shown > 0 and not enabled:
        caret_lines = _caret_captions(view, spans)
        lines.extend(caret_lines)

    return "\n".join(lines)


def _fmt_range(start: int, end: int) -> str:
    """Format a byte range like ``0x00`` or ``0x00\u20130x07`` for the caption."""
    if end - start <= 1:
        return f"0x{start:02x}"
    return f"0x{start:02x}\u20130x{end - 1:02x}"


def _render_row(
    base: int,
    row: bytes,
    spans: List[Span],
    *,
    enabled: bool,
) -> str:
    """Render one 16-byte row: ``OFFSET   hex hex  hex hex   |ascii|``."""
    offset_col = _paint(f"{base:08x}", _DIM, enabled=enabled)

    hex_cells: List[str] = []
    ascii_cells: List[str] = []
    for i in range(BYTES_PER_ROW):
        idx = base + i
        if i < len(row):
            byte = row[i]
            highlighted = any(s.contains(idx) for s in spans)
            h = _hex_pair(byte)
            a = chr(byte) if _is_printable(byte) else _NONPRINT
            if highlighted:
                h = _paint(h, _INVERSE, _CYAN, enabled=enabled)
                a = _paint(a, _INVERSE, _CYAN, enabled=enabled)
            hex_cells.append(h)
            ascii_cells.append(a)
        else:
            hex_cells.append("  ")  # pad short final row so columns line up
            ascii_cells.append(" ")

        if i == GROUP_SIZE - 1:
            hex_cells.append("")  # marker → becomes the mid-row gap on join

    hex_col = _join_hex(hex_cells)
    ascii_col = "".join(ascii_cells)
    return f"{offset_col}  {hex_col}  |{ascii_col}|"


def _join_hex(cells: List[str]) -> str:
    """Join hex cells with single spaces, and a double space at the group gap.

    The empty-string marker inserted after :data:`GROUP_SIZE` bytes turns into an
    extra space here, giving the familiar ``.... ....  .... ....`` split without
    special-casing widths when cells contain ANSI codes.
    """
    out: List[str] = []
    for cell in cells:
        if cell == "":
            out.append(" ")  # the group gap (added on top of the normal space)
            continue
        out.append(cell)
        out.append(" ")
    # Drop the trailing separator space for a clean right edge.
    if out and out[-1] == " ":
        out.pop()
    return "".join(out)


def _caret_captions(view: bytes, spans: List[Span]) -> List[str]:
    """Plain-mode captions: underline each span with carets + its label.

    Only emitted when colour is off (piped/`NO_COLOR`), so the highlight is still
    visible in plain text and the golden tests have a stable, greppable marker.
    Each caption is anchored to the row where the span begins.
    """
    lines: List[str] = []
    # Width of the offset column + the two spaces before the hex block.
    prefix_w = 8 + 2

    for span in spans:
        if span.start >= len(view):
            continue
        row_base = (span.start // BYTES_PER_ROW) * BYTES_PER_ROW
        start_in_row = span.start - row_base
        # Clamp the span's end to the row it starts on so a long span doesn't
        # run its carets off the end of a single row.
        last_index = min(span.end - 1, row_base + BYTES_PER_ROW - 1)
        last_in_row = last_index - row_base
        start_col = _hex_column_offset(start_in_row)
        # The caret run covers from the first hex digit of the start byte to the
        # last hex digit of the final byte (its column offset + 2 hex chars).
        end_col = _hex_column_offset(last_in_row) + 2
        pad = " " * (prefix_w + start_col)
        carets = _CARET * max(end_col - start_col, 1)
        lines.append(f"{pad}{carets} {span.label}")
    return lines


def _hex_column_offset(byte_index_in_row: int) -> int:
    """Column offset (chars) of a byte's hex pair within the hex block.

    Each byte occupies 3 columns (two hex digits + one separator space). One
    extra space is added once the group boundary has been crossed, matching the
    double space :func:`_join_hex` inserts after :data:`GROUP_SIZE` bytes, so
    plain-mode carets line up under the right hex digits.
    """
    cols = byte_index_in_row * 3
    if byte_index_in_row >= GROUP_SIZE:
        cols += 1
    return cols
