"""End-to-end CLI tests for the ``peek`` subcommand (M3).

Checks that ``bytebite peek <file>`` renders the annotated hex view, honours
``--bytes``, keeps identify-mode untouched, and returns the right exit codes for
missing files / directories. ``NO_COLOR`` is set so output is plain and
assertable.
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


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


def test_peek_known_file_renders_and_labels(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d")
    rc = cli.main(["peek", path])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "hex peek" in out
    assert "89 50 4e 47" in out  # magic in hex
    assert "PNG image magic" in out  # caption label
    assert "|.PNG" in out  # ascii column


def test_peek_bytes_option_limits_output(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", bytes(range(64)))
    rc = cli.main(["peek", "--bytes", "16", path])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "showing 16 byte(s)" in out
    data_rows = [ln for ln in out.splitlines() if ln.startswith("000000")]
    assert len(data_rows) == 1


def test_peek_short_bytes_flag(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", bytes(range(64)))
    rc = cli.main(["peek", "-n", "16", path])
    assert rc == cli.EXIT_OK
    assert "showing 16 byte(s)" in capsys.readouterr().out


def test_peek_unknown_blob_exit_zero(tmp_path, capsys) -> None:
    # peek is a viewer: even an unidentifiable blob renders and exits 0.
    path = _write(tmp_path, "blob.bin", b"no known magic here whatsoever")
    rc = cli.main(["peek", path])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "hex peek" in out
    assert "highlighting" not in out


def test_peek_missing_file_exit_two(tmp_path, capsys) -> None:
    rc = cli.main(["peek", str(tmp_path / "nope.bin")])
    assert rc == cli.EXIT_ERROR
    assert "no such file" in capsys.readouterr().err.lower()


def test_peek_directory_exit_two(tmp_path, capsys) -> None:
    rc = cli.main(["peek", str(tmp_path)])
    assert rc == cli.EXIT_ERROR
    assert "directory" in capsys.readouterr().err.lower()


def test_peek_no_ansi_when_no_color(tmp_path, capsys) -> None:
    path = _write(tmp_path, "pic.png", b"\x89PNG\r\n\x1a\n")
    cli.main(["peek", path])
    assert "\x1b[" not in capsys.readouterr().out


def test_identify_mode_unaffected_by_peek_wiring(tmp_path, capsys) -> None:
    # The bare `bytebite <file>` form must still identify (regression guard).
    path = _write(tmp_path, "pic.png", b"\x89PNG\r\n\x1a\n")
    rc = cli.main([path])
    assert rc == cli.EXIT_OK
    assert "PNG image" in capsys.readouterr().out


def test_peek_via_subprocess(tmp_path) -> None:
    import os

    path = _write(tmp_path, "a.out", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 32)
    env = dict(os.environ, NO_COLOR="1")
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "peek", path],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == cli.EXIT_OK
    assert "ELF executable magic" in result.stdout
    assert "7f 45 4c 46" in result.stdout
