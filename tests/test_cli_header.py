"""End-to-end CLI tests for the ``header`` subcommand (issue #23).

``bytebite header <file>`` prints *only* the parsed header — no hex art, no
prose — as clean, machine-readable output. These tests pin the JSON shape for
each field-decoded format (PNG IHDR, ELF, ZIP local, WAV fmt), the graceful
empty-fields fallback for an identified-but-undecoded format, the unknown-file
and stdin paths, ``--quiet``, and the stable exit codes (0 identified, 1
unknown, 2 error). ``NO_COLOR`` is autouse so output stays plain and assertable.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bytebite import cli

# Minimal but sufficient header bytes for each field-decoded format.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR"
    b"\x00\x00\x07\x80\x00\x00\x04\x38\x08\x06\x00\x00\x00"
)
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 + b"\x02\x00\x3e\x00" + b"\x00" * 8
# ZIP local file header: PK\x03\x04, version 20, no flags, method 8 (deflate).
ZIP = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 20
# Canonical PCM WAV header: RIFF ... WAVE fmt  ... 2ch 44100Hz 16-bit.
WAV = (
    b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
    b"\x01\x00\x02\x00\x44\xac\x00\x00\x10\xb1\x02\x00\x04\x00\x10\x00"
)
UNKNOWN = b"no known magic header at all, just some text bytes"


def _write(tmp_path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


def _one_json_line(out: str) -> dict:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, out
    return json.loads(lines[0])


# --------------------------------------------------------------------------- #
# JSON shape per decoded format
# --------------------------------------------------------------------------- #
def test_header_png_json_shape(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_OK
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["identified"] is True
    assert payload["format"] == "PNG image"
    assert payload["category"] == "image"
    assert payload["magic"] == {"offset": 0, "end": 8, "hex": "\\x89PNG\\x0d\\x0a\\x1a\\x0a"}
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["width"]["value"] == 1920
    assert by_name["height"]["value"] == 1080
    assert by_name["colour type"]["label"] == "truecolour+alpha (RGBA)"
    # Every field carries the documented, stable keys.
    for f in payload["fields"]:
        assert set(f) == {
            "name", "offset", "end", "size", "type", "value", "label", "hex", "note"
        }


def test_header_elf_json_shape(tmp_path, capsys) -> None:
    path = _write(tmp_path, "a.out", ELF)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_OK
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["format"] == "ELF executable"
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["class"]["label"] == "64-bit"
    assert by_name["machine"]["label"] == "x86-64"


def test_header_zip_json_shape(tmp_path, capsys) -> None:
    path = _write(tmp_path, "a.zip", ZIP)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_OK
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["format"] == "ZIP archive"
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["method"]["label"] == "deflate"


def test_header_wav_json_shape(tmp_path, capsys) -> None:
    path = _write(tmp_path, "a.wav", WAV)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_OK
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["format"] == "WAV audio"
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["sample rate"]["value"] == 44100
    assert by_name["channels"]["value"] == 2
    assert by_name["audio format"]["label"] == "PCM"


# --------------------------------------------------------------------------- #
# Empty-fields fallback, unknown, exit codes, quiet, stdin
# --------------------------------------------------------------------------- #
def test_header_identified_without_layout_has_empty_fields(tmp_path, capsys) -> None:
    # GIF is identified but has no field-layout decoder → consistent shape.
    path = _write(tmp_path, "a.gif", b"GIF89a" + b"\x00" * 16)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_OK
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["identified"] is True
    assert payload["fields"] == []


def test_header_no_hex_art_in_text_mode(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main(["header", path])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "PNG image" in out
    assert "width" in out and "1920" in out
    # No hex dump rows (peek-style "00000000  89 50 ...").
    assert "89 50 4e 47" not in out
    assert "hex peek" not in out


def test_header_unknown_exits_one(tmp_path, capsys) -> None:
    path = _write(tmp_path, "mystery.bin", UNKNOWN)
    rc = cli.main(["header", path, "--json"])
    assert rc == cli.EXIT_UNIDENTIFIED
    payload = _one_json_line(capsys.readouterr().out)
    assert payload["identified"] is False
    assert payload["format"] is None
    assert payload["magic"] is None
    assert payload["fields"] == []


def test_header_quiet_prints_only_name(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main(["header", path, "-q"])
    assert rc == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "PNG image"


def test_header_quiet_unknown_is_silent(tmp_path, capsys) -> None:
    path = _write(tmp_path, "mystery.bin", UNKNOWN)
    rc = cli.main(["header", path, "-q"])
    assert rc == cli.EXIT_UNIDENTIFIED
    assert capsys.readouterr().out.strip() == ""


def test_header_missing_file_exits_two(capsys) -> None:
    rc = cli.main(["header", "/no/such/file"])
    assert rc == cli.EXIT_ERROR


def test_header_json_and_quiet_mutually_exclusive(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["header", "x", "--json", "-q"])


def test_header_stdin_json(tmp_path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "header", "-", "--json"],
        input=PNG,
        capture_output=True,
    )
    assert result.returncode == cli.EXIT_OK
    payload = json.loads(result.stdout.decode())
    assert payload["format"] == "PNG image"
    assert payload["source"] == "<stdin>"
