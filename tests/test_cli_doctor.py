"""CLI tests for the ``doctor`` subcommand — issue #10.

``bytebite doctor`` reports the effective registry (built-in vs custom
signatures), the custom-signatures directory, and any drop-in files that failed
to load. ``--json`` emits the same as one machine-readable line.
"""

from __future__ import annotations

import json

import pytest

from bytebite import cli, registry


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture()
def sigdir(tmp_path, monkeypatch):
    d = tmp_path / "signatures.d"
    d.mkdir()
    monkeypatch.setenv("BYTEBITE_SIGNATURES_DIR", str(d))
    registry.reset_cache()
    yield d
    registry.reset_cache()


def _write(dirpath, name, obj):
    (dirpath / name).write_text(json.dumps(obj), encoding="utf-8")


def test_doctor_clean_exits_zero(sigdir, capsys) -> None:
    rc = cli.main(["doctor"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "registry check" in out
    assert "built-in" in out
    assert "OK" in out


def test_doctor_reports_custom_count(sigdir, capsys) -> None:
    _write(sigdir, "acme.json", {
        "name": "ACME blob", "category": "database", "magic": "hex:41434d45",
    })
    rc = cli.main(["doctor"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "1 custom" in out
    assert "ACME blob" in out


def test_doctor_reports_errors_and_nonzero_exit(sigdir, capsys) -> None:
    _write(sigdir, "bad.json", {"name": "X", "category": "nope", "magic": "hex:00"})
    rc = cli.main(["doctor"])
    assert rc == cli.EXIT_UNIDENTIFIED
    out = capsys.readouterr().out
    assert "errors" in out
    assert "unknown category" in out


def test_doctor_json_shape(sigdir, capsys) -> None:
    _write(sigdir, "acme.json", {
        "name": "ACME blob", "category": "database", "magic": "hex:41434d45",
    })
    rc = cli.main(["doctor", "--json"])
    assert rc == cli.EXIT_OK
    doc = json.loads(capsys.readouterr().out)
    assert doc["tool"] == "bytebite"
    assert doc["signatures"]["custom"] == 1
    assert doc["signatures"]["total"] == (
        doc["signatures"]["builtin"] + doc["signatures"]["custom"]
    )
    assert doc["custom"]["loaded"] == ["ACME blob"]
    assert doc["ok"] is True


def test_doctor_json_reports_errors(sigdir, capsys) -> None:
    _write(sigdir, "bad.json", {"name": "X", "category": "nope", "magic": "hex:00"})
    rc = cli.main(["doctor", "--json"])
    assert rc == cli.EXIT_UNIDENTIFIED
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False
    assert len(doc["custom"]["errors"]) == 1
    assert doc["custom"]["errors"][0]["source"].endswith("bad.json")


def test_doctor_json_single_line(sigdir, capsys) -> None:
    cli.main(["doctor", "--json"])
    out = capsys.readouterr().out
    assert len([ln for ln in out.splitlines() if ln.strip()]) == 1
