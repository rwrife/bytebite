"""Tests for custom (user-supplied) signature loading — issue #10."""

from __future__ import annotations

import json

import pytest

from bytebite import registry
from bytebite.custom import (
    decode_bytes_field,
    load_custom_signatures,
    signatures_dir,
)


@pytest.fixture()
def sigdir(tmp_path, monkeypatch):
    """Point custom-signature discovery at a temp dir and reset the cache."""
    d = tmp_path / "signatures.d"
    d.mkdir()
    monkeypatch.setenv("BYTEBITE_SIGNATURES_DIR", str(d))
    registry.reset_cache()
    yield d
    registry.reset_cache()


def _write(dirpath, name, obj):
    (dirpath / name).write_text(json.dumps(obj), encoding="utf-8")


# --- decode_bytes_field -----------------------------------------------------


def test_decode_hex():
    assert decode_bytes_field("hex:41 42 43") == b"ABC"


def test_decode_base64():
    assert decode_bytes_field("base64:QUJD") == b"ABC"


def test_decode_literal_utf8():
    assert decode_bytes_field("ACME") == b"ACME"


def test_decode_bad_hex_raises():
    with pytest.raises(ValueError):
        decode_bytes_field("hex:zzzz")


# --- discovery / env override ----------------------------------------------


def test_signatures_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BYTEBITE_SIGNATURES_DIR", str(tmp_path))
    assert signatures_dir() == tmp_path


def test_signatures_dir_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("BYTEBITE_SIGNATURES_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert signatures_dir() == tmp_path / "bytebite" / "signatures.d"


def test_missing_dir_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("BYTEBITE_SIGNATURES_DIR", str(tmp_path / "nope"))
    report = load_custom_signatures()
    assert report.count == 0
    assert report.ok
    assert report.files_scanned == 0


# --- loading valid signatures ----------------------------------------------


def test_loads_single_object(sigdir):
    _write(sigdir, "acme.json", {
        "name": "ACME blob",
        "category": "database",
        "magic": "hex:41434d45",
        "description": "ACME store.",
    })
    report = load_custom_signatures()
    assert report.ok
    assert report.count == 1
    sig = report.signatures[0]
    assert sig.name == "ACME blob"
    assert sig.magic == b"ACME"


def test_loads_array_of_signatures(sigdir):
    _write(sigdir, "many.json", [
        {"name": "A", "category": "data", "magic": "hex:aa"},
        {"name": "B", "category": "data", "magic": "hex:bb"},
    ])
    report = load_custom_signatures()
    assert report.count == 2
    assert {s.name for s in report.signatures} == {"A", "B"}


def test_mask_and_offset(sigdir):
    _write(sigdir, "m.json", {
        "name": "Masked",
        "category": "data",
        "magic": "hex:ffff",
        "mask": "hex:ff00",
        "offset": 4,
    })
    report = load_custom_signatures()
    sig = report.signatures[0]
    assert sig.offset == 4
    assert sig.mask == b"\xff\x00"


# --- error handling ---------------------------------------------------------


def test_bad_json_is_reported_not_fatal(sigdir):
    (sigdir / "broken.json").write_text("{ not json", encoding="utf-8")
    report = load_custom_signatures()
    assert report.count == 0
    assert not report.ok
    assert "invalid JSON" in report.errors[0][1]


def test_unknown_category_rejected(sigdir):
    _write(sigdir, "c.json", {"name": "X", "category": "nope", "magic": "hex:00"})
    report = load_custom_signatures()
    assert not report.ok
    assert "unknown category" in report.errors[0][1]


def test_missing_key_rejected(sigdir):
    _write(sigdir, "c.json", {"name": "X", "category": "data"})
    report = load_custom_signatures()
    assert not report.ok
    assert "magic" in report.errors[0][1]


def test_mask_length_mismatch_rejected(sigdir):
    _write(sigdir, "c.json", {
        "name": "X", "category": "data", "magic": "hex:ffff", "mask": "hex:ff",
    })
    report = load_custom_signatures()
    assert not report.ok
    assert "mask" in report.errors[0][1].lower()


def test_field_layout_rejected(sigdir):
    _write(sigdir, "c.json", {
        "name": "X", "category": "data", "magic": "hex:00", "field_layout": "PNG image",
    })
    report = load_custom_signatures()
    assert not report.ok
    assert "field_layout" in report.errors[0][1]


def test_one_bad_entry_in_array_still_loads_others(sigdir):
    _write(sigdir, "mix.json", [
        {"name": "Good", "category": "data", "magic": "hex:aa"},
        {"name": "Bad", "category": "nope", "magic": "hex:bb"},
    ])
    report = load_custom_signatures()
    assert report.count == 1
    assert report.signatures[0].name == "Good"
    assert len(report.errors) == 1


# --- registry merge / shadowing --------------------------------------------


def test_custom_signature_is_identifiable(sigdir):
    _write(sigdir, "acme.json", {
        "name": "ACME blob", "category": "database", "magic": "hex:41434d45",
    })
    from bytebite.identify import identify

    matches = identify(b"ACME\x00\x00")
    assert matches
    assert matches[0].name == "ACME blob"


def test_custom_shadows_builtin_by_name(sigdir):
    _write(sigdir, "png.json", {
        "name": "PNG image", "category": "image",
        "magic": "hex:89504e470d0a1a0a", "description": "custom png",
    })
    sigs = registry.effective_signatures()
    pngs = [s for s in sigs if s.name == "PNG image"]
    assert len(pngs) == 1
    assert pngs[0].description == "custom png"


def test_effective_signatures_includes_builtins(sigdir):
    # No custom files: count matches the built-in registry.
    from bytebite.signatures import all_signatures

    assert len(registry.effective_signatures()) == len(all_signatures())
