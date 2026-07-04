"""Smoke tests for the CLI scaffold and wiring.

These verify the skeleton is wired up correctly: version reporting, the
help-on-no-args behaviour, and that the console entry point / ``python -m`` path
resolve. Behaviour tests for identification live in ``test_cli_identify.py``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import bytebite
from bytebite import cli


def test_version_is_a_nonempty_string() -> None:
    assert isinstance(bytebite.__version__, str)
    assert bytebite.__version__.strip()


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse's version action raises SystemExit(0) after printing.
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert bytebite.__version__ in out


def test_short_version_flag_matches_long(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["-V"])
    out = capsys.readouterr().out
    assert bytebite.__version__ in out


def test_no_args_prints_help_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()
    assert cli.PROG in out


def test_python_dash_m_entrypoint_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert bytebite.__version__ in result.stdout


def test_python_dash_m_no_args_shows_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
