"""End-to-end CLI tests for M5: ``--json``, ``--quiet`` and stable exit codes.

Covers the scripting contract for both ``bytebite <file>`` (identify) and
``bytebite peek <file>``:

* ``--json`` emits exactly one parseable JSON line with the documented shape.
* ``--quiet`` prints just the format name (nothing on unknown).
* Exit codes are stable: 0 identified, 1 unknown, 2 read/usage error.
* Neither machine mode leaks ANSI colour.

``NO_COLOR`` is set autouse so even a (hypothetical) TTY wouldn't colour output.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from bytebite import cli

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d"
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64
UNKNOWN = b"no known magic header at all, just text"


def _write(tmp_path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


# --------------------------------------------------------------------------- #
# identify --json
# --------------------------------------------------------------------------- #
def test_identify_json_known_shape_and_exit_zero(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main([path, "--json"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1  # exactly one JSON line
    doc = json.loads(lines[0])
    assert doc["identified"] is True
    assert doc["tool"] == "bytebite"
    assert doc["schema_version"] >= 1
    assert doc["source"] == path
    assert doc["match"]["name"] == "PNG image"
    assert doc["match"]["offset"] == 0
    assert doc["match"]["end"] == 8


def test_identify_json_unknown_exit_one(tmp_path, capsys) -> None:
    path = _write(tmp_path, "blob.bin", UNKNOWN)
    rc = cli.main([path, "--json"])
    assert rc == cli.EXIT_UNIDENTIFIED
    doc = json.loads(capsys.readouterr().out)
    assert doc["identified"] is False
    assert doc["match"] is None


def test_identify_json_missing_file_exit_two(tmp_path, capsys) -> None:
    rc = cli.main([str(tmp_path / "nope.bin"), "--json"])
    assert rc == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert "no such file" in captured.err.lower()
    assert captured.out == ""  # nothing on stdout for an error


def test_identify_json_no_ansi(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    cli.main([path, "--json"])
    assert "\x1b[" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# identify --quiet
# --------------------------------------------------------------------------- #
def test_identify_quiet_prints_only_name(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main([path, "--quiet"])
    assert rc == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "PNG image"


def test_identify_quiet_short_flag(tmp_path, capsys) -> None:
    path = _write(tmp_path, "a.out", ELF)
    rc = cli.main([path, "-q"])
    assert rc == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "ELF executable"


def test_identify_quiet_unknown_prints_nothing_exit_one(tmp_path, capsys) -> None:
    path = _write(tmp_path, "blob.bin", UNKNOWN)
    rc = cli.main([path, "--quiet"])
    assert rc == cli.EXIT_UNIDENTIFIED
    assert capsys.readouterr().out.strip() == ""


def test_json_and_quiet_are_mutually_exclusive(tmp_path) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    with pytest.raises(SystemExit) as excinfo:
        cli.main([path, "--json", "--quiet"])
    # argparse exits 2 on a usage error.
    assert excinfo.value.code == cli.EXIT_ERROR


# --------------------------------------------------------------------------- #
# peek --json / --quiet
# --------------------------------------------------------------------------- #
def test_peek_json_shape_and_spans(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main(["peek", path, "--bytes", "16", "--json"])
    assert rc == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["identified"] is True
    assert doc["match"]["name"] == "PNG image"
    peek = doc["peek"]
    assert peek["bytes_shown"] == len(PNG)  # PNG head is < 16 bytes
    assert peek["total_read"] == len(PNG)
    assert peek["hex"].startswith("89504e47")
    # First span is always the magic (identification proof). With M6 the short
    # PNG head here also reaches the IHDR length field (offset 8–12), so a
    # decoded-field span follows the magic span.
    assert peek["spans"][0] == {
        "start": 0,
        "end": 8,
        "label": "PNG image magic",
        "hex": "89504e470d0a1a0a",
    }
    assert {
        "start": 8,
        "end": 12,
        "label": "IHDR length",
        "hex": "0000000d",
    } in peek["spans"]
    # The richer typed field view carries the decoded value + note.
    ihdr_len = next(f for f in peek["fields"] if f["name"] == "IHDR length")
    assert ihdr_len["value"] == 13
    assert ihdr_len["type"] == "u32be"


def test_peek_json_unknown_has_empty_spans_exit_zero(tmp_path, capsys) -> None:
    # peek is a viewer: unknown blob still renders/exits 0, spans empty.
    path = _write(tmp_path, "blob.bin", UNKNOWN)
    rc = cli.main(["peek", path, "--json"])
    assert rc == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["identified"] is False
    assert doc["match"] is None
    assert doc["peek"]["spans"] == []


def test_peek_quiet_prints_name(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    rc = cli.main(["peek", path, "--quiet"])
    assert rc == cli.EXIT_OK
    assert capsys.readouterr().out.strip() == "PNG image"


def test_peek_json_no_ansi(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", PNG)
    cli.main(["peek", path, "--json"])
    assert "\x1b[" not in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# stdin + subprocess (the real pipeline path)
# --------------------------------------------------------------------------- #
def test_identify_json_from_stdin_subprocess() -> None:
    env = dict(os.environ, NO_COLOR="1")
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "-", "--json"],
        input=PNG,
        capture_output=True,
        env=env,
    )
    assert result.returncode == cli.EXIT_OK
    doc = json.loads(result.stdout)
    assert doc["source"] == "<stdin>"
    assert doc["match"]["name"] == "PNG image"


def test_quiet_json_flags_before_dash_stdin_subprocess() -> None:
    # Flags may precede the ``-`` source token too.
    env = dict(os.environ, NO_COLOR="1")
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "--quiet", "-"],
        input=ELF,
        capture_output=True,
        env=env,
    )
    assert result.returncode == cli.EXIT_OK
    assert result.stdout.strip() == b"ELF executable"


def test_peek_json_from_stdin_subprocess() -> None:
    env = dict(os.environ, NO_COLOR="1")
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "peek", "-", "--bytes", "16", "--json"],
        input=PNG,
        capture_output=True,
        env=env,
    )
    assert result.returncode == cli.EXIT_OK
    doc = json.loads(result.stdout)
    assert doc["source"] == "<stdin>"
    assert doc["peek"]["spans"][0]["label"] == "PNG image magic"
