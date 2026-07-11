"""Tests for ``bytebite find`` — fuzzy structured header search (issue #9).

Covers predicate parsing (all operators, error cases), the field-matching
engine (exact, enum-label and numeric-comparison matching, AND semantics), and
the CLI wiring end-to-end (human output, ``--json``, exit codes).
"""

from __future__ import annotations

import struct

import pytest

from bytebite.cli import main
from bytebite.find import (
    Predicate,
    PredicateError,
    evaluate_file,
    find_matches,
    parse_predicate,
)


# --- fixtures ---------------------------------------------------------------


def _png_bytes(width=1920, height=1080, depth=8, color=6) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + bytes([depth, color, 0, 0, 0])
    )


def _wav_bytes(sample_rate=44100, channels=2) -> bytes:
    return (
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)  # PCM
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", sample_rate * channels * 2)
        + struct.pack("<H", channels * 2)
        + struct.pack("<H", 16)
    )


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# --- predicate parsing ------------------------------------------------------


@pytest.mark.parametrize(
    "clause, name, op, value",
    [
        ("width=1920", "width", "=", "1920"),
        ("width >= 1920", "width", ">=", "1920"),
        ("height<=1080", "height", "<=", "1080"),
        ("width>100", "width", ">", "100"),
        ("width<4000", "width", "<", "4000"),
        ("method=deflate", "method", "=", "deflate"),
    ],
)
def test_parse_predicate_ok(clause, name, op, value):
    pred = parse_predicate(clause)
    assert pred == Predicate(name=name, op=op, value=value)


@pytest.mark.parametrize("clause", ["nofooo", "=1920", "  =x"])
def test_parse_predicate_rejects_malformed(clause):
    with pytest.raises(PredicateError):
        parse_predicate(clause)


# --- engine -----------------------------------------------------------------


def test_exact_numeric_match(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(width=1920))
    m = evaluate_file(p, [parse_predicate("width=1920")])
    assert m is not None
    assert m.format == "PNG image"
    assert m.matched[0].name == "width"
    assert m.matched[0].value == 1920


def test_exact_numeric_non_match(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(width=800))
    assert evaluate_file(p, [parse_predicate("width=1920")]) is None


def test_enum_label_match(tmp_path):
    # PNG colour type 6 → "truecolour+alpha (RGBA)"; match on the label.
    p = _write(tmp_path, "a.png", _png_bytes(color=6))
    m = evaluate_file(p, [parse_predicate("colour type=truecolour+alpha (RGBA)")])
    assert m is not None


def test_enum_raw_value_match(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(color=6))
    m = evaluate_file(p, [parse_predicate("colour type=6")])
    assert m is not None


def test_numeric_comparisons(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(width=1920, height=1080))
    assert evaluate_file(p, [parse_predicate("width>=1920")]) is not None
    assert evaluate_file(p, [parse_predicate("width>1920")]) is None
    assert evaluate_file(p, [parse_predicate("height<=1080")]) is not None
    assert evaluate_file(p, [parse_predicate("height<1080")]) is None


def test_and_semantics(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(width=1920, height=1080))
    assert (
        evaluate_file(
            p, [parse_predicate("width=1920"), parse_predicate("height=1080")]
        )
        is not None
    )
    assert (
        evaluate_file(
            p, [parse_predicate("width=1920"), parse_predicate("height=720")]
        )
        is None
    )


def test_case_insensitive_field_name(tmp_path):
    p = _write(tmp_path, "a.png", _png_bytes(width=1920))
    assert evaluate_file(p, [parse_predicate("WIDTH=1920")]) is not None


def test_unidentified_file_no_match(tmp_path):
    p = _write(tmp_path, "x.bin", b"no signature here whatsoever, just text")
    assert evaluate_file(p, [parse_predicate("width=1920")]) is None


def test_format_without_fields_no_match(tmp_path):
    # GZIP is identified but has no field layout → never matches a field query.
    p = _write(tmp_path, "a.gz", b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03rest")
    assert evaluate_file(p, [parse_predicate("method=deflate")]) is None


def test_find_matches_filters_directory(tmp_path):
    a = _write(tmp_path, "a.png", _png_bytes(width=1920))
    b = _write(tmp_path, "b.png", _png_bytes(width=800))
    w = _write(tmp_path, "c.wav", _wav_bytes(sample_rate=48000))
    results = find_matches([a, b, w], [parse_predicate("width=1920")])
    assert [m.path for m in results] == [a]


def test_wav_sample_rate_search(tmp_path):
    w = _write(tmp_path, "c.wav", _wav_bytes(sample_rate=48000))
    assert evaluate_file(w, [parse_predicate("sample rate=48000")]) is not None
    assert evaluate_file(w, [parse_predicate("sample rate>=44100")]) is not None


# --- CLI --------------------------------------------------------------------


def test_cli_find_human_output(tmp_path, capsys):
    a = _write(tmp_path, "a.png", _png_bytes(width=1920))
    _write(tmp_path, "b.png", _png_bytes(width=800))
    code = main(["find", "--field", "width=1920", a, str(tmp_path / "b.png")])
    out = capsys.readouterr().out
    assert code == 0
    assert a in out
    assert "PNG image" in out and "width=1920" in out
    assert "b.png" not in out


def test_cli_find_json(tmp_path, capsys):
    import json

    a = _write(tmp_path, "a.png", _png_bytes(width=1920))
    code = main(["find", "--field", "width=1920", "--json", a])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "find"
    assert payload["query"] == ["width=1920"]
    assert payload["count"] == 1
    assert payload["matches"][0]["path"] == a
    assert payload["matches"][0]["fields"][0]["value"] == 1920


def test_cli_find_no_match_exit_1(tmp_path, capsys):
    a = _write(tmp_path, "a.png", _png_bytes(width=800))
    code = main(["find", "--field", "width=1920", a])
    assert code == 1
    assert "no files matched" in capsys.readouterr().err


def test_cli_find_bad_predicate_exit_2(tmp_path, capsys):
    a = _write(tmp_path, "a.png", _png_bytes())
    code = main(["find", "--field", "nonsense", a])
    assert code == 2
    assert "invalid --field" in capsys.readouterr().err


def test_cli_find_requires_predicate_exit_2(tmp_path, capsys):
    a = _write(tmp_path, "a.png", _png_bytes())
    code = main(["find", a])
    assert code == 2
    assert "need at least one --field" in capsys.readouterr().err
