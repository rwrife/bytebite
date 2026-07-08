"""Tests for field-level header decoding (M6).

These exercise :mod:`bytebite.fields` directly: the :class:`Field` model and its
validation, each decoder, enum labelling, graceful truncation, and the per-format
layouts (PNG IHDR, ELF header incl. endianness, ZIP local header, WAV fmt chunk)
decoding real header bytes to the expected values.
"""

from __future__ import annotations

import struct

import pytest

from bytebite.fields import (
    Field,
    decode_field,
    decode_fields,
    decoded_fields_for,
    fields_for,
    has_field_detail,
)


# --------------------------------------------------------------------------- #
# Field model + validation
# --------------------------------------------------------------------------- #
def test_field_end_is_offset_plus_size() -> None:
    assert Field("x", 4, 2, "u16le").end == 6


def test_field_rejects_non_positive_size() -> None:
    with pytest.raises(ValueError):
        Field("x", 0, 0, "u8")


def test_field_rejects_negative_offset() -> None:
    with pytest.raises(ValueError):
        Field("x", -1, 1, "u8")


def test_field_rejects_unknown_type() -> None:
    with pytest.raises(ValueError):
        Field("x", 0, 1, "float128")


# --------------------------------------------------------------------------- #
# Decoders
# --------------------------------------------------------------------------- #
def test_u8_decoder() -> None:
    d = decode_field(Field("b", 0, 1, "u8"), b"\x2a")
    assert d is not None and d.value == 42


def test_u16_endianness() -> None:
    data = b"\x01\x02"
    assert decode_field(Field("be", 0, 2, "u16be"), data).value == 0x0102
    assert decode_field(Field("le", 0, 2, "u16le"), data).value == 0x0201


def test_u32_endianness() -> None:
    data = struct.pack(">I", 1920)
    assert decode_field(Field("be", 0, 4, "u32be"), data).value == 1920
    assert decode_field(Field("le", 0, 4, "u32le"), data).value == struct.unpack(
        "<I", data
    )[0]


def test_ascii_decoder_shows_nonprintables_as_dots() -> None:
    d = decode_field(Field("s", 0, 4, "ascii"), b"AB\x00\x7f")
    assert d.value == "AB.."


def test_hex_and_magic_decoders() -> None:
    assert decode_field(Field("h", 0, 2, "hex"), b"\xde\xad").value == "dead"
    assert decode_field(Field("m", 0, 2, "magic"), b"\xca\xfe").value == "cafe"


def test_enum_label_applied_and_display() -> None:
    fld = Field("method", 0, 1, "u8", enum={8: "deflate"})
    d = decode_field(fld, b"\x08")
    assert d.value == 8
    assert d.label == "deflate"
    assert d.display() == "deflate (8)"


def test_enum_miss_leaves_label_none() -> None:
    fld = Field("method", 0, 1, "u8", enum={8: "deflate"})
    d = decode_field(fld, b"\x63")  # 99, not in enum
    assert d.label is None
    assert d.display() == "99"


def test_decode_field_returns_none_when_too_short() -> None:
    assert decode_field(Field("w", 4, 4, "u32be"), b"\x00\x00") is None


def test_decode_fields_skips_overrunning_fields() -> None:
    fields = (Field("a", 0, 2, "u16be"), Field("b", 8, 4, "u32be"))
    # Only 4 bytes: first field fits, second overruns and is skipped.
    out = decode_fields(fields, b"\x00\x01\x02\x03")
    assert [d.name for d in out] == ["a"]


# --------------------------------------------------------------------------- #
# Layout registry
# --------------------------------------------------------------------------- #
def test_has_field_detail_for_target_formats() -> None:
    for name in ["PNG image", "ELF executable", "ZIP archive", "WAV audio"]:
        assert has_field_detail(name), name


def test_has_field_detail_false_for_plain_format() -> None:
    assert not has_field_detail("GZIP archive")
    assert not has_field_detail("nonexistent format")


def test_fields_for_unknown_is_empty() -> None:
    assert fields_for("nope") == ()


# --------------------------------------------------------------------------- #
# PNG IHDR
# --------------------------------------------------------------------------- #
def _png_header(width: int, height: int, depth=8, color=6) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + bytes([depth, color, 0, 0, 0])
    )


def test_png_fields_decode_dimensions_and_color() -> None:
    data = _png_header(1920, 1080, depth=8, color=6)
    fields = {d.name: d for d in decoded_fields_for("PNG image", data)}
    assert fields["width"].value == 1920
    assert fields["height"].value == 1080
    assert fields["bit depth"].value == 8
    assert fields["colour type"].label == "truecolour+alpha (RGBA)"
    assert fields["chunk type"].value == "IHDR"
    assert fields["compression"].label == "deflate"


# --------------------------------------------------------------------------- #
# ELF header (endianness-sensitive)
# --------------------------------------------------------------------------- #
def _elf_header(elf_class: int, data_enc: int, etype: int, machine: int) -> bytes:
    ident = bytes([0x7F]) + b"ELF" + bytes([elf_class, data_enc, 1, 0]) + b"\x00" * 8
    pack = ">H" if data_enc == 2 else "<H"
    return ident + struct.pack(pack, etype) + struct.pack(pack, machine) + b"\x00" * 40


def test_elf_little_endian_x86_64() -> None:
    data = _elf_header(2, 1, 2, 0x3E)
    f = {d.name: d for d in decoded_fields_for("ELF executable", data)}
    assert f["class"].label == "64-bit"
    assert f["data"].label == "little-endian"
    assert f["type"].label == "executable"
    assert f["machine"].label == "x86-64"


def test_elf_big_endian_powerpc_switches_decoder() -> None:
    data = _elf_header(1, 2, 3, 0x14)
    f = {d.name: d for d in decoded_fields_for("ELF executable", data)}
    assert f["class"].label == "32-bit"
    assert f["data"].label == "big-endian"
    assert f["type"].label == "shared object"
    # If endianness were ignored, machine would decode as 0x1400, not 0x14.
    assert f["machine"].value == 0x14
    assert f["machine"].label == "PowerPC"


# --------------------------------------------------------------------------- #
# ZIP local file header
# --------------------------------------------------------------------------- #
def test_zip_local_header_fields() -> None:
    data = (
        b"PK\x03\x04"
        + struct.pack("<H", 20)  # version needed
        + struct.pack("<H", 0)  # flags
        + struct.pack("<H", 8)  # method: deflate
        + struct.pack("<H", 0)  # time
        + struct.pack("<H", 0)  # date
        + struct.pack("<I", 0)  # crc
        + struct.pack("<I", 1000)  # compressed
        + struct.pack("<I", 4096)  # uncompressed
        + struct.pack("<H", 8)  # name len
        + struct.pack("<H", 0)  # extra len
        + b"test.txt"
    )
    f = {d.name: d for d in decoded_fields_for("ZIP archive", data)}
    assert f["method"].label == "deflate"
    assert f["compressed size"].value == 1000
    assert f["uncompressed size"].value == 4096
    assert f["name length"].value == 8


# --------------------------------------------------------------------------- #
# WAV fmt chunk
# --------------------------------------------------------------------------- #
def _wav_header(channels: int, sample_rate: int, bps: int, fmt=1) -> bytes:
    byte_rate = sample_rate * channels * bps // 8
    block_align = channels * bps // 8
    return (
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", fmt)
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", bps)
    )


def test_wav_fmt_chunk_fields() -> None:
    data = _wav_header(2, 44100, 16)
    f = {d.name: d for d in decoded_fields_for("WAV audio", data)}
    assert f["audio format"].label == "PCM"
    assert f["channels"].value == 2
    assert f["sample rate"].value == 44100
    assert f["bits/sample"].value == 16
    assert f["byte rate"].value == 44100 * 2 * 16 // 8


def test_wav_float_format_label() -> None:
    data = _wav_header(1, 48000, 32, fmt=3)
    f = {d.name: d for d in decoded_fields_for("WAV audio", data)}
    assert f["audio format"].label == "IEEE float"
