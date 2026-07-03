"""End-to-end CLI tests for the identification path (M2).

Exercises ``bytebite <file>`` for a known format, an unknown blob, and a
missing file — checking both output and the process exit codes that scripting
will rely on.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from bytebite import cli


def _write(tmp_path, name: str, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_identify_known_file_exit_zero(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d")
    rc = cli.main([path])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "PNG image" in out
    assert "image" in out
    assert "%" in out  # confidence rendered


def test_identify_unknown_file_exit_one(tmp_path, capsys) -> None:
    path = _write(tmp_path, "blob.bin", b"not a known magic header at all")
    rc = cli.main([path])
    assert rc == cli.EXIT_UNIDENTIFIED
    out = capsys.readouterr().out
    assert "unidentified" in out.lower()


def test_missing_file_exit_two(tmp_path, capsys) -> None:
    rc = cli.main([str(tmp_path / "does-not-exist.bin")])
    assert rc == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "no such file" in err.lower()


def test_directory_argument_exit_two(tmp_path, capsys) -> None:
    rc = cli.main([str(tmp_path)])
    assert rc == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "directory" in err.lower()


def test_elf_identified_via_subprocess(tmp_path) -> None:
    path = _write(tmp_path, "a.out", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64)
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", path],
        capture_output=True,
        text=True,
    )
    assert result.returncode == cli.EXIT_OK
    assert "ELF executable" in result.stdout


def test_no_color_env_strips_ansi(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    path = _write(tmp_path, "pic.png", b"\x89PNG\r\n\x1a\n")
    cli.main([path])
    out = capsys.readouterr().out
    assert "\x1b[" not in out  # no ANSI escape sequences
