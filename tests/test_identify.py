"""Tests for the identification engine (M2).

Uses tiny, hand-built header fixtures — just enough magic bytes for each seed
format — to prove :func:`bytebite.identify.identify` returns the right format,
a sensible confidence, and the correct matched range. No real files needed.
"""

from __future__ import annotations

from bytebite.identify import best_match, identify, identify_path, read_head

# Minimal leading bytes for each seed format, padded a little so a 4-byte read
# has room. Values are the genuine magic signatures.
FIXTURES = {
    "PNG image": b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d",
    "GIF image": b"GIF89a\x10\x00\x10\x00",
    "JPEG image": b"\xff\xd8\xff\xe0\x00\x10JFIF",
    "PDF document": b"%PDF-1.7\n%\xe2\xe3",
    "ZIP archive": b"PK\x03\x04\x14\x00\x00\x00",
    "GZIP archive": b"\x1f\x8b\x08\x00\x00\x00\x00\x00",
    "ELF executable": b"\x7fELF\x02\x01\x01\x00",
    "PE executable": b"MZ\x90\x00\x03\x00\x00\x00",
    # --- M4 formats -------------------------------------------------------
    "BMP image": b"BM\x36\x00\x00\x00\x00\x00",
    "ICO icon": b"\x00\x00\x01\x00\x01\x00\x10\x10",
    "WAV audio": b"RIFF\x24\x08\x00\x00WAVEfmt ",
    "SQLite database": b"SQLite format 3\x00",
    "Parquet data": b"PAR1\x00\x00\x00\x00",
    "WebAssembly module": b"\x00asm\x01\x00\x00\x00",
    "Java class": b"\xca\xfe\xba\xbe\x00\x00\x00\x34",
    "7-Zip archive": b"7z\xbc\xaf\x27\x1c\x00\x04",
    "XZ archive": b"\xfd7zXZ\x00\x00\x00",
    "ZSTD archive": b"\x28\xb5\x2f\xfd\x00\x00\x00\x00",
    "BZIP2 archive": b"BZh9\x31\x41\x59\x26",
}

# TAR's ``ustar`` magic lives at offset 257, so its fixture needs a full first
# file header of padding in front. Kept separate from the offset-0 FIXTURES.
TAR_FIXTURE = b"./file.txt" + b"\x00" * 247 + b"ustar\x0000"


def test_each_seed_format_is_identified() -> None:
    for expected_name, head in FIXTURES.items():
        match = best_match(head)
        assert match is not None, f"{expected_name}: nothing matched"
        assert match.name == expected_name, (
            f"expected {expected_name}, got {match.name}"
        )


def test_tar_identified_via_offset_magic() -> None:
    match = best_match(TAR_FIXTURE)
    assert match is not None
    assert match.name == "TAR archive"
    assert match.offset == 257
    assert match.matched_bytes == b"ustar"


def test_tiny_and_empty_inputs_do_not_crash() -> None:
    # M4 guarantees graceful handling of tiny/empty files.
    for head in (b"", b"M", b"\x00", b"PK", b"RIFF"):
        # Must not raise; unknown-ish tiny inputs simply return no/what-matches.
        result = identify(head)
        assert isinstance(result, list)


def test_confidence_is_in_unit_range_and_positive() -> None:
    for head in FIXTURES.values():
        match = best_match(head)
        assert match is not None
        assert 0.0 < match.confidence <= 0.99


def test_longer_magic_beats_shorter() -> None:
    # PNG (8 bytes) should read as far more confident than PE (2 bytes).
    png = best_match(FIXTURES["PNG image"])
    pe = best_match(FIXTURES["PE executable"])
    assert png is not None and pe is not None
    assert png.confidence > pe.confidence


def test_matched_range_points_at_the_magic() -> None:
    match = best_match(FIXTURES["PNG image"])
    assert match is not None
    assert match.offset == 0
    assert match.end == 8  # \x89PNG\r\n\x1a\n is 8 bytes
    assert match.matched_bytes == b"\x89PNG\r\n\x1a\n"


def test_jpeg_marker_family_matches_via_mask() -> None:
    # Exif JPEGs start FF D8 FF E1 — the masked third-magic byte should accept it.
    match = best_match(b"\xff\xd8\xff\xe1\x00\x10Exif")
    assert match is not None
    assert match.name == "JPEG image"
    # matched_bytes reflects the *actual* input, not the wildcard template.
    assert match.matched_bytes == b"\xff\xd8\xff\xe1"


def test_gif87a_and_gif89a_both_identify_as_gif() -> None:
    for head in (b"GIF87a\x01\x00", b"GIF89a\x01\x00"):
        match = best_match(head)
        assert match is not None
        assert match.name == "GIF image"


def test_unknown_bytes_return_no_match() -> None:
    assert best_match(b"totally random not-a-format bytes") is None
    assert identify(b"totally random not-a-format bytes") == []
    assert best_match(b"") is None


def test_identify_returns_sorted_by_confidence() -> None:
    matches = identify(FIXTURES["PNG image"])
    confidences = [m.confidence for m in matches]
    assert confidences == sorted(confidences, reverse=True)


def test_read_head_and_identify_path(tmp_path) -> None:
    p = tmp_path / "mystery.blob"
    p.write_bytes(FIXTURES["ELF executable"] + b"\x00" * 100)
    head = read_head(str(p))
    assert head.startswith(b"\x7fELF")
    matches = identify_path(str(p))
    assert matches and matches[0].name == "ELF executable"


def test_read_head_respects_size_limit(tmp_path) -> None:
    p = tmp_path / "big.bin"
    p.write_bytes(b"\x00" * 10000)
    assert len(read_head(str(p), size=16)) == 16
