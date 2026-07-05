"""Tests for the signature registry (M2).

These check the :class:`Signature` model's matching semantics (including masks
and offsets) and a couple of invariants about the seeded registry so a bad
signature edit trips a test rather than shipping.
"""

from __future__ import annotations

import pytest

from bytebite.signatures import SIGNATURES, Signature, all_signatures


def test_signature_matches_exact_magic() -> None:
    sig = Signature(name="X", category="test", magic=b"ABCD")
    assert sig.matches(b"ABCD....")
    assert not sig.matches(b"ABXD....")


def test_signature_too_short_head_does_not_match() -> None:
    sig = Signature(name="X", category="test", magic=b"ABCD")
    assert not sig.matches(b"AB")
    assert not sig.matches(b"")


def test_signature_respects_offset() -> None:
    sig = Signature(name="X", category="test", magic=b"CD", offset=2)
    assert sig.matches(b"ABCD")
    assert not sig.matches(b"CDAB")


def test_signature_mask_allows_wildcard_bytes() -> None:
    # Third byte is a full wildcard (mask 0x00), so it may be anything.
    sig = Signature(
        name="X",
        category="test",
        magic=b"\xff\xd8\xff\x00",
        mask=b"\xff\xff\xff\x00",
    )
    assert sig.matches(b"\xff\xd8\xff\xe0")  # JFIF-style
    assert sig.matches(b"\xff\xd8\xff\xe1")  # Exif-style
    assert not sig.matches(b"\xff\xd8\x00\xe0")  # third real byte wrong


def test_signature_end_property() -> None:
    sig = Signature(name="X", category="test", magic=b"ABCD", offset=3)
    assert sig.end == 7


def test_signature_rejects_empty_magic() -> None:
    with pytest.raises(ValueError):
        Signature(name="X", category="test", magic=b"")


def test_signature_rejects_mask_length_mismatch() -> None:
    with pytest.raises(ValueError):
        Signature(name="X", category="test", magic=b"ABCD", mask=b"\xff")


def test_signature_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        Signature(name="X", category="test", magic=b"AB", offset=-1)


def test_registry_covers_the_eight_seed_formats() -> None:
    names = {s.name for s in SIGNATURES}
    for expected in [
        "PNG image",
        "JPEG image",
        "GIF image",
        "PDF document",
        "ZIP archive",
        "GZIP archive",
        "ELF executable",
        "PE executable",
    ]:
        assert expected in names, f"missing seed format: {expected}"


def test_registry_categories_are_known() -> None:
    known = {"image", "archive", "executable", "document", "audio", "database"}
    for sig in SIGNATURES:
        assert sig.category in known, f"{sig.name} has odd category {sig.category!r}"


def test_registry_reaches_m4_breadth() -> None:
    # M4 grows the registry toward ~20 everyday formats. Assert both the raw
    # signature count and the number of distinct format names clear that bar.
    assert len(SIGNATURES) >= 20
    assert len({s.name for s in SIGNATURES}) >= 20


def test_registry_covers_the_m4_additions() -> None:
    names = {s.name for s in SIGNATURES}
    for expected in [
        "WAV audio",
        "MP3 audio",
        "SQLite database",
        "Parquet data",
        "WebAssembly module",
        "Java class",
        "BMP image",
        "TAR archive",
        "7-Zip archive",
        "XZ archive",
        "ICO icon",
    ]:
        assert expected in names, f"missing M4 format: {expected}"


def test_tar_signature_uses_the_ustar_offset() -> None:
    tar = next(s for s in SIGNATURES if s.name == "TAR archive")
    assert tar.offset == 257
    assert tar.magic == b"ustar"


def test_all_signatures_returns_readonly_tuple() -> None:
    sigs = all_signatures()
    assert isinstance(sigs, tuple)
    assert len(sigs) == len(SIGNATURES)
