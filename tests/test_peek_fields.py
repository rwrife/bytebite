"""Peek rendering tests for field-level annotation (M6).

Complements ``test_peek.py`` (which covers the M3 magic-only dump). Here we check
that a format with a field layout gets a decoded-field legend, that the magic
caret caption still anchors correctly, that field spans light up the dump, and
that the legend survives colour mode (where carets are dropped).
"""

from __future__ import annotations

import struct

from bytebite.identify import identify
from bytebite.peek import _spans_for_match, render_peek


def _png(width=1920, height=1080, depth=8, color=6) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + bytes([depth, color, 0, 0, 0])
    )


def _best(data: bytes):
    matches = identify(data)
    assert matches
    return matches[0]


def test_spans_include_magic_then_fields() -> None:
    data = _png()
    spans = _spans_for_match(_best(data), data)
    assert spans[0].kind == "magic"
    assert spans[0].label == "PNG image magic"
    field_spans = [s for s in spans if s.kind == "field"]
    labels = {s.label for s in field_spans}
    assert {"width", "height", "colour type"} <= labels


def test_legend_lists_decoded_values_plain_mode() -> None:
    out = render_peek(_png(), _best(_png()), bytes_shown=32, use_color=False)
    assert "decoded header fields:" in out
    assert "width" in out and "1920" in out
    assert "height" in out and "1080" in out
    assert "truecolour+alpha (RGBA)" in out


def test_field_count_noted_in_caption() -> None:
    out = render_peek(_png(), _best(_png()), bytes_shown=32, use_color=False)
    assert "header field(s) decoded" in out


def test_magic_caret_still_present_and_anchored() -> None:
    data = _png()
    out = render_peek(data, _best(data), bytes_shown=32, use_color=False)
    lines = out.splitlines()
    row0 = next(ln for ln in lines if ln.startswith("00000000"))
    caret_line = next(ln for ln in lines if "^" in ln)
    assert "PNG image magic" in caret_line
    assert caret_line.index("^") == row0.index("89")


def test_only_magic_gets_carets_not_every_field() -> None:
    # Field values are listed in the legend, not underlined with carets, so the
    # plain-mode output stays readable regardless of field count.
    out = render_peek(_png(), _best(_png()), bytes_shown=32, use_color=False)
    caret_lines = [ln for ln in out.splitlines() if "^" in ln]
    assert len(caret_lines) == 1  # just the magic underline


def test_legend_survives_colour_mode() -> None:
    out = render_peek(_png(), _best(_png()), bytes_shown=32, use_color=True)
    assert "^" not in out  # carets dropped in colour mode
    assert "\x1b[" in out  # colour codes present
    # The decoded values must still be visible via the legend.
    assert "width" in out and "1920" in out
    assert "sample rate" not in out  # (sanity: PNG has no such field)


def test_truncated_header_decodes_only_fitting_fields() -> None:
    # Cut off mid-IHDR: width fits, height does not.
    data = _png()[:20]  # up to width's last byte
    spans = _spans_for_match(_best(data), data)
    field_labels = {s.label for s in spans if s.kind == "field"}
    assert "width" in field_labels
    assert "height" not in field_labels


def test_unknown_blob_has_no_field_legend() -> None:
    blob = b"just some text with no signature here at all"
    out = render_peek(blob, None, use_color=False)
    assert "decoded header fields:" not in out


def test_format_without_layout_has_no_legend() -> None:
    # GZIP is identified but has no field layout → magic only, no legend.
    gz = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03rest"
    out = render_peek(gz, _best(gz), use_color=False)
    assert "decoded header fields:" not in out
    assert "GZIP archive magic" in out  # magic caret still there
