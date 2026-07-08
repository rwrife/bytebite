"""CLI tests for ``--list-formats`` (M6).

``bytebite --list-formats`` prints every known format and marks the ones with
field-level header detail; ``--json`` emits the same as one machine-readable
line. It is independent of any input file and always exits 0.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bytebite import cli


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


def test_list_formats_exits_zero_and_lists_formats(capsys) -> None:
    rc = cli.main(["--list-formats"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "PNG image" in out
    assert "WAV audio" in out
    # The four field-detail formats are flagged.
    for name in ["PNG image", "ELF executable", "ZIP archive", "WAV audio"]:
        line = next(ln for ln in out.splitlines() if ln.strip().startswith(name))
        assert "fields" in line, f"{name} should be marked as having field detail"


def test_list_formats_does_not_flag_plain_formats(capsys) -> None:
    cli.main(["--list-formats"])
    out = capsys.readouterr().out
    gzip_line = next(ln for ln in out.splitlines() if "GZIP archive" in ln)
    assert "fields" not in gzip_line


def test_list_formats_json_shape(capsys) -> None:
    rc = cli.main(["--list-formats", "--json"])
    assert rc == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["tool"] == "bytebite"
    assert doc["schema_version"] >= 1
    names = {f["name"]: f for f in doc["formats"]}
    assert names["PNG image"]["fields"] is True
    assert names["GZIP archive"]["fields"] is False
    assert names["ELF executable"]["category"] == "executable"


def test_list_formats_json_is_single_line(capsys) -> None:
    cli.main(["--list-formats", "--json"])
    out = capsys.readouterr().out
    assert len([ln for ln in out.splitlines() if ln.strip()]) == 1


def test_list_formats_no_ansi(capsys) -> None:
    cli.main(["--list-formats"])
    assert "\x1b[" not in capsys.readouterr().out


def test_list_formats_counts_four_with_detail(capsys) -> None:
    cli.main(["--list-formats"])
    header = capsys.readouterr().out.splitlines()[0]
    assert "4 with field-level header detail" in header


def test_list_formats_via_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "--list-formats"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "PNG image" in result.stdout
