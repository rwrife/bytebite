"""Golden-string tests for the annotated hex peek (M3).

The dump is intentionally deterministic (fixed 16-byte rows, plain-mode carets),
so we can assert on exact rendered strings. Colour is forced off with
``use_color=False`` throughout — piped/`NO_COLOR` output is what scripts and
these tests see, and it must stay stable.
"""

from __future__ import annotations

from bytebite.identify import Match, identify
from bytebite.peek import DEFAULT_BYTES, render_peek
from bytebite.signatures import Signature

PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR\x00\x00\x00\x10"


def _png_match() -> Match:
    matches = identify(PNG_HEADER)
    assert matches, "PNG header should identify"
    return matches[0]


def test_dump_has_offset_hex_and_ascii_columns() -> None:
    out = render_peek(PNG_HEADER, _png_match(), use_color=False)
    lines = out.splitlines()
    # First data row: offset gutter, hex, and the |ascii| gutter.
    row0 = next(ln for ln in lines if ln.startswith("00000000"))
    assert row0.startswith("00000000  ")
    assert "89 50 4e 47 0d 0a 1a 0a" in row0  # PNG magic in hex
    assert "|.PNG........IHDR|" in row0  # ASCII column, non-printables as dots


def test_magic_range_is_labelled_with_carets_in_plain_mode() -> None:
    out = render_peek(PNG_HEADER, _png_match(), use_color=False)
    # The caption underlines the 8-byte magic and names it.
    assert "^^^^^^^^^^^^^^^^^^^^^^^ PNG image magic" in out
    assert "highlighting PNG image magic at 0x00\u20130x07" in out


def test_carets_align_under_the_magic_bytes() -> None:
    out = render_peek(PNG_HEADER, _png_match(), use_color=False)
    lines = out.splitlines()
    row0 = next(ln for ln in lines if ln.startswith("00000000"))
    caret_line = next(ln for ln in lines if "^" in ln)
    # The first caret should sit exactly under the first hex digit of byte 0.
    assert caret_line.index("^") == row0.index("89")


def test_plain_mode_has_no_ansi_escapes() -> None:
    out = render_peek(PNG_HEADER, _png_match(), use_color=False)
    assert "\x1b[" not in out


def test_color_mode_emits_ansi_and_drops_carets() -> None:
    out = render_peek(PNG_HEADER, _png_match(), use_color=True)
    assert "\x1b[" in out  # colour codes present
    assert "^" not in out  # colour speaks for itself; no caret caption


def test_bytes_option_limits_rows_shown() -> None:
    out = render_peek(PNG_HEADER, _png_match(), bytes_shown=8, use_color=False)
    assert "showing 8 byte(s)" in out
    # Only one data row for 8 bytes.
    data_rows = [ln for ln in out.splitlines() if ln.startswith("000000")]
    assert len(data_rows) == 1


def test_default_bytes_constant_used_when_unspecified() -> None:
    big = bytes(range(256))
    out = render_peek(big, None, use_color=False)
    assert f"showing {DEFAULT_BYTES} byte(s)" in out


def test_unknown_blob_renders_without_highlight() -> None:
    blob = b"plain text, nothing to see here at all really"
    out = render_peek(blob, None, use_color=False)
    assert "highlighting" not in out
    assert "^" not in out
    assert "|plain text, noth|" in out  # first 16 bytes in ASCII column


def test_zero_bytes_renders_gracefully() -> None:
    out = render_peek(PNG_HEADER, _png_match(), bytes_shown=0, use_color=False)
    assert "showing 0 byte(s)" in out
    assert "no bytes to show" in out
    assert "^" not in out  # nothing visible → no caret caption


def test_empty_data_does_not_crash() -> None:
    out = render_peek(b"", None, use_color=False)
    assert "showing 0 byte(s)" in out


def test_span_crossing_group_boundary_aligns() -> None:
    # A 5-byte magic at offset 6 straddles the mid-row (8-byte) gap.
    sig = Signature(name="TestFmt", category="test", magic=b"ABCDE", offset=6)
    data = bytes(range(20))
    match = Match(signature=sig, confidence=0.9, matched_bytes=data[6:11])
    out = render_peek(data, match, use_color=False, bytes_shown=16)
    lines = out.splitlines()
    row0 = next(ln for ln in lines if ln.startswith("00000000"))
    caret_line = next(ln for ln in lines if "^" in ln)
    # First caret under byte 6's hex, last caret under byte 10's (0x0a) hex.
    assert caret_line.index("^") == row0.index(" 06 ") + 1
    last_caret = caret_line.rindex("^")
    assert row0.index("0a") <= last_caret <= row0.index("0a") + 1


def test_partial_final_row_pads_ascii_gutter() -> None:
    # 20 bytes → second row has 4 bytes; the |ascii| gutter must still close.
    out = render_peek(PNG_HEADER, _png_match(), bytes_shown=20, use_color=False)
    lines = out.splitlines()
    row1 = next(ln for ln in lines if ln.startswith("00000010"))
    assert row1.rstrip().endswith("|")
    assert row1.count("|") == 2
