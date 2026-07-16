"""Tests for the ``entropy`` subcommand (issue #21).

``bytebite entropy <file>`` slices a blob into blocks and reports each block's
Shannon entropy plus a heuristic verdict. These tests pin the entropy maths
edge cases (all-same-byte = 0.0, uniform 256 bytes = 8.0), block bucketing
(including a short trailing block), the JSON schema shape, stdin support, the
``--quiet`` line, the ``--block`` validation error, and that colour is off under
``NO_COLOR``. ``NO_COLOR`` is autouse so text output stays plain and assertable.
"""

from __future__ import annotations

import json
import math

import pytest

from bytebite import cli
from bytebite.entropy import DEFAULT_BLOCK, scan_entropy, shannon_entropy


@pytest.fixture(autouse=True)
def _no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _run(argv):
    return cli.main(["entropy", *argv])


# --- entropy maths -------------------------------------------------------


def test_all_same_byte_is_zero():
    assert shannon_entropy(b"\x00" * 1024) == 0.0
    assert shannon_entropy(b"A" * 7) == 0.0


def test_uniform_all_values_is_eight():
    # One of each byte value → perfectly uniform → 8.0 bits/byte.
    data = bytes(range(256))
    assert shannon_entropy(data) == pytest.approx(8.0)


def test_two_equal_symbols_is_one_bit():
    # 50/50 split of two values → exactly 1 bit/byte.
    data = b"\x00\x01" * 64
    assert shannon_entropy(data) == pytest.approx(1.0)


def test_empty_block_is_zero():
    assert shannon_entropy(b"") == 0.0


# --- block bucketing -----------------------------------------------------


def test_block_bucketing_with_short_tail():
    # 300 bytes, block 256 → two blocks; the second is a 44-byte tail.
    report = scan_entropy(b"\x00" * 300, block_size=256)
    assert len(report.blocks) == 2
    assert report.blocks[0].offset == 0
    assert report.blocks[0].end == 256
    assert report.blocks[1].offset == 256
    assert report.blocks[1].end == 300  # short trailing block


def test_default_block_size():
    report = scan_entropy(b"\x00" * (DEFAULT_BLOCK + 1))
    assert report.block_size == DEFAULT_BLOCK
    assert len(report.blocks) == 2


def test_bad_block_size_raises():
    with pytest.raises(ValueError):
        scan_entropy(b"data", block_size=0)


# --- CLI: JSON shape -----------------------------------------------------


def test_json_shape(tmp_path, capsys):
    data = bytes(range(256)) + b"\x00" * 44
    f = _write(tmp_path, "blob.bin", data)
    code = _run(["--json", "--block", "256", f])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["tool"] == "bytebite"
    assert "schema_version" in out
    assert out["source"] == f
    assert out["block_size"] == 256
    assert out["verdict"] in {
        "looks compressed/encrypted",
        "mostly text/structured",
        "mixed",
    }
    assert len(out["blocks"]) == 2
    first = out["blocks"][0]
    assert first["offset"] == 0
    assert first["end"] == 256
    assert first["entropy"] == pytest.approx(8.0)
    assert out["blocks"][1]["end"] == 300
    assert isinstance(out["overall"], float)


def test_high_entropy_verdict(tmp_path, capsys):
    # A full uniform 256-byte block is maximally high-entropy.
    f = _write(tmp_path, "rand.bin", bytes(range(256)) * 4)
    code = _run(["--json", f])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["overall"] == pytest.approx(8.0)
    assert out["verdict"] == "looks compressed/encrypted"


def test_low_entropy_verdict(tmp_path, capsys):
    f = _write(tmp_path, "zeros.bin", b"\x00" * 1024)
    code = _run(["--json", f])
    out = json.loads(capsys.readouterr().out)
    assert out["overall"] == 0.0
    assert out["verdict"] == "mostly text/structured"


# --- CLI: text / quiet / stdin -------------------------------------------


def test_text_output_no_color(tmp_path, capsys):
    f = _write(tmp_path, "z.bin", b"\x00" * 300)
    code = _run([f])
    out = capsys.readouterr().out
    assert code == 0
    assert "\x1b[" not in out  # no ANSI under NO_COLOR
    assert "entropy" in out
    assert "overall" in out
    assert "block 256B" in out


def test_quiet_output(tmp_path, capsys):
    f = _write(tmp_path, "z.bin", b"\x00" * 512)
    code = _run(["-q", f])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out == "0.00 mostly text/structured"


def test_stdin(monkeypatch, capsys):
    import io

    blob = b"\x00\x01" * 256
    monkeypatch.setattr(
        "sys.stdin", type("S", (), {"buffer": io.BytesIO(blob)})()
    )
    code = _run(["--json", "-"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["source"] == "<stdin>"
    assert out["overall"] == pytest.approx(1.0)


def test_bad_block_cli_error(tmp_path, capsys):
    f = _write(tmp_path, "z.bin", b"\x00" * 16)
    code = _run(["--block", "0", f])
    err = capsys.readouterr().err
    assert code == 2
    assert "block" in err.lower()


def test_missing_file_error(capsys):
    code = _run(["/no/such/file/xyz.bin"])
    err = capsys.readouterr().err
    assert code == 2
    assert "no such file" in err
