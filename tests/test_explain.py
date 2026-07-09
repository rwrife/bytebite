"""Tests for ``bytebite explain <format>`` (issue #7).

``explain`` is the file-less pocket reference: given a format name it prints the
magic bytes and the documented header layout, reusing the signature registry and
the M6 field tables. These tests cover the resolver (case/extension/mnemonic/
ambiguity/typo), the human render, the ``--json`` payload shape, exit codes, and
the CLI wiring (including the ``python -m bytebite`` subcommand path).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from bytebite import cli
from bytebite import explain as explain_mod


@pytest.fixture(autouse=True)
def _no_color(monkeypatch) -> None:
    # Keep human output ANSI-free so assertions match plain text.
    monkeypatch.setenv("NO_COLOR", "1")


# --- resolver ---------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("png", "PNG image"),
        ("PNG", "PNG image"),
        ("PNG image", "PNG image"),
        (".png", "PNG image"),
        ("  png  ", "PNG image"),
        ("elf", "ELF executable"),
        ("wav", "WAV audio"),
        (".wav", "WAV audio"),
        ("zip", "ZIP archive"),  # mnemonic prefers the plain, shortest name
        ("sqlite", "SQLite database"),  # substring fallback
    ],
)
def test_resolve_hits(token, expected) -> None:
    name, candidates = explain_mod.resolve_format(token)
    assert name == expected
    assert candidates == [expected]


def test_resolve_full_name_of_qualified_variant() -> None:
    # The qualified variant is reachable by its exact full name even though the
    # bare ``zip`` mnemonic maps to the primary "ZIP archive".
    name, _ = explain_mod.resolve_format("zip archive (empty)")
    assert name == "ZIP archive (empty)"


def test_resolve_unknown_returns_no_name() -> None:
    name, candidates = explain_mod.resolve_format("definitely-not-a-format")
    assert name is None
    assert candidates == []  # nothing close enough


def test_resolve_typo_suggests_close_name() -> None:
    name, candidates = explain_mod.resolve_format("pgn")
    assert name is None
    assert "PNG image" in candidates


# --- explain() tri-state ----------------------------------------------------


def test_explain_ok_status() -> None:
    info, candidates, status = explain_mod.explain("png")
    assert status == "ok"
    assert info is not None
    assert info.name == "PNG image"
    assert candidates == ["PNG image"]


def test_explain_unknown_status() -> None:
    info, candidates, status = explain_mod.explain("foobar-xyz")
    assert status == "unknown"
    assert info is None


def test_explain_ambiguous_status_when_no_primary(monkeypatch) -> None:
    # Force a genuine same-length mnemonic tie to exercise the ambiguous branch.
    monkeypatch.setattr(
        explain_mod, "_canonical_names", lambda: ["FOO bar", "FOO baz"]
    )
    info, candidates, status = explain_mod.explain("foo")
    assert status == "ambiguous"
    assert info is None
    assert set(candidates) == {"FOO bar", "FOO baz"}


# --- FormatInfo gathering ---------------------------------------------------


def test_format_info_png_has_fields() -> None:
    info = explain_mod.format_info("PNG image")
    assert info.category == "image"
    assert info.has_fields
    field_names = [f.name for f in info.fields]
    assert "width" in field_names and "height" in field_names


def test_format_info_gzip_has_no_fields() -> None:
    info = explain_mod.format_info("GZIP archive")
    assert not info.has_fields
    assert info.fields == ()


def test_format_info_mp3_collects_multiple_signatures() -> None:
    info = explain_mod.format_info("MP3 audio")
    assert len(info.signatures) == 2  # ID3 tag + raw frame sync


def test_format_info_elf_uses_little_endian_view() -> None:
    info = explain_mod.format_info("ELF executable")
    # The dynamic ELF layout resolved with the LE probe → 16-bit ints are LE.
    type_field = next(f for f in info.fields if f.name == "type")
    assert type_field.type == "u16le"


# --- human render -----------------------------------------------------------


def test_render_png_contains_headline_magic_and_fields() -> None:
    info = explain_mod.format_info("PNG image")
    out = explain_mod.render_explain(info)
    assert "PNG image" in out
    assert "category: image" in out
    assert "Magic:" in out
    assert "Header fields:" in out
    assert "width" in out and "height" in out
    # Enum values are spelled out.
    assert "Known values:" in out
    assert "truecolour" in out


def test_render_no_fields_message() -> None:
    info = explain_mod.format_info("GZIP archive")
    out = explain_mod.render_explain(info)
    assert "none documented yet" in out
    assert "Known values:" not in out


def test_render_wav_shows_wildcards() -> None:
    info = explain_mod.format_info("WAV audio")
    out = explain_mod.render_explain(info)
    assert "??" in out  # masked size bytes rendered as wildcards
    assert "wildcard" in out


def test_render_elf_notes_endianness() -> None:
    info = explain_mod.format_info("ELF executable")
    out = explain_mod.render_explain(info)
    assert "little-endian view" in out


# --- JSON payload -----------------------------------------------------------


def test_explain_dict_shape() -> None:
    info = explain_mod.format_info("PNG image")
    doc = explain_mod.explain_dict(info)
    assert doc["tool"] == "bytebite"
    assert doc["schema_version"] >= 1
    fmt = doc["format"]
    assert fmt["name"] == "PNG image"
    assert fmt["category"] == "image"
    assert isinstance(fmt["signatures"], list) and fmt["signatures"]
    assert fmt["signatures"][0]["offset"] == 0
    names = [f["name"] for f in fmt["fields"]]
    assert "width" in names
    # Enum keys are stringified so the JSON is always valid.
    colour = next(f for f in fmt["fields"] if f["name"] == "colour type")
    assert colour["enum"]["2"].startswith("truecolour")


def test_explain_dict_masked_flag() -> None:
    info = explain_mod.format_info("WAV audio")
    doc = explain_mod.explain_dict(info)
    assert doc["format"]["signatures"][0]["masked"] is True


# --- CLI wiring -------------------------------------------------------------


def test_cli_explain_exit_ok(capsys) -> None:
    rc = cli.main(["explain", "png"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "PNG image" in out


def test_cli_explain_json_single_line(capsys) -> None:
    rc = cli.main(["explain", "elf", "--json"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["format"]["name"] == "ELF executable"


def test_cli_explain_no_ansi_in_json(capsys) -> None:
    cli.main(["explain", "png", "--json"])
    assert "\x1b[" not in capsys.readouterr().out


def test_cli_explain_unknown_exits_error(capsys) -> None:
    rc = cli.main(["explain", "totally-bogus"])
    assert rc == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "unknown format" in err
    assert "--list-formats" in err


def test_cli_explain_typo_suggests(capsys) -> None:
    rc = cli.main(["explain", "pgn"])
    assert rc == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "Did you mean" in err
    assert "PNG image" in err


def test_cli_explain_extension_form(capsys) -> None:
    rc = cli.main(["explain", ".wav"])
    assert rc == cli.EXIT_OK
    assert "WAV audio" in capsys.readouterr().out


def test_cli_explain_via_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "explain", "png"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "PNG image" in result.stdout
    assert "Header fields:" in result.stdout


def test_cli_explain_json_via_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bytebite", "explain", "wav", "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    doc = json.loads(result.stdout)
    assert doc["format"]["name"] == "WAV audio"
