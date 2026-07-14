"""End-to-end tests for the ``diff`` subcommand (issue #22).

``bytebite diff <fileA> <fileB>`` identifies both files and shows how their
recognised headers differ. These tests pin: same-format-equal,
same-format-differing-fields, cross-format, an unknown side, the JSON shape, the
stdin path, and the exit-code contract (0 both identified, 1 at least one
unknown, 2 error). ``NO_COLOR`` is autouse so output stays plain and assertable.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bytebite import cli

# 1920x1080 truecolour+alpha PNG header.
PNG_1920 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
    b"\x00\x00\x07\x80\x00\x00\x04\x38\x08\x06\x00\x00\x00"
)
# 640x480 truecolour+alpha PNG header (same format, differing fields).
PNG_640 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
    b"\x00\x00\x02\x80\x00\x00\x01\xe0\x08\x06\x00\x00\x00"
)
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 + b"\x02\x00\x3e\x00" + b"\x00" * 8
UNKNOWN = b"\x00\x01\x02\x03 not a known format at all " + b"\xff" * 8


@pytest.fixture(autouse=True)
def _no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _run(argv):
    return cli.main(["diff", *argv])


def test_same_format_equal(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.png", PNG_1920)
    code = _run(["--json", a, b])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["same_format"] is True
    assert out["a"]["format"] == "PNG image"
    assert out["b"]["format"] == "PNG image"
    # Every shared field is equal.
    for fd in out["field_diffs"]:
        assert fd["equal"] is True


def test_same_format_differing_fields(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.png", PNG_640)
    code = _run(["--json", a, b])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["same_format"] is True
    by_field = {fd["field"]: fd for fd in out["field_diffs"]}
    assert by_field["width"]["a"] == 1920
    assert by_field["width"]["b"] == 640
    assert by_field["width"]["equal"] is False
    assert by_field["height"]["equal"] is False
    # colour type is the same on both → equal.
    assert by_field["colour type"]["equal"] is True


def test_cross_format(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.elf", ELF)
    code = _run(["--json", a, b])
    out = json.loads(capsys.readouterr().out)
    assert code == 0  # both identified
    assert out["same_format"] is False
    assert out["a"]["format"] == "PNG image"
    assert out["b"]["format"] == "ELF executable"
    # Disjoint field sets → every diff is one-sided (equal is None).
    for fd in out["field_diffs"]:
        assert fd["equal"] is None


def test_unknown_side_exit_1(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.bin", UNKNOWN)
    code = _run(["--json", a, b])
    out = json.loads(capsys.readouterr().out)
    assert code == 1  # at least one unknown
    assert out["a"]["identified"] is True
    assert out["b"]["identified"] is False
    assert out["same_format"] is False
    # No decoded fields on the unknown side → all diffs one-sided.
    for fd in out["field_diffs"]:
        assert fd["b"] is None


def test_text_output_shows_both(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.png", PNG_640)
    code = _run([a, b])
    text = capsys.readouterr().out
    assert code == 0
    assert "PNG image" in text
    assert "same format" in text
    assert "width" in text
    assert "\u2260" in text  # a differing field is marked with ≠


def test_missing_file_is_error(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    code = _run([a, str(tmp_path / "nope.bin")])
    err = capsys.readouterr().err
    assert code == 2
    assert "no such file" in err


def test_both_stdin_is_error(capsys):
    code = _run(["-", "-"])
    err = capsys.readouterr().err
    assert code == 2
    assert "stdin" in err


def test_stdin_side(tmp_path):
    a = _write(tmp_path, "a.png", PNG_1920)
    proc = subprocess.run(
        [sys.executable, "-m", "bytebite", "diff", a, "-", "--json"],
        input=PNG_640,
        capture_output=True,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout.decode())
    assert out["a"]["source"] == a
    assert out["b"]["source"] == "<stdin>"
    assert out["same_format"] is True


def test_json_shape(tmp_path, capsys):
    a = _write(tmp_path, "a.png", PNG_1920)
    b = _write(tmp_path, "b.png", PNG_640)
    _run(["--json", a, b])
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {
        "schema_version",
        "tool",
        "a",
        "b",
        "same_format",
        "same_magic_offset",
        "field_diffs",
    }
    assert out["tool"] == "bytebite"
    side = out["a"]
    assert set(side) == {
        "source",
        "identified",
        "format",
        "category",
        "confidence",
        "magic",
    }
    fd = out["field_diffs"][0]
    assert set(fd) == {
        "field",
        "a",
        "b",
        "a_label",
        "b_label",
        "a_hex",
        "b_hex",
        "equal",
    }
