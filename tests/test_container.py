"""Tests for container awareness (issue #8).

Builds tiny, real ZIP archives on disk whose *member names* mimic the tell-tale
layout of each ZIP-based format (docx, xlsx, pptx, jar, apk, epub, odt), then
proves :func:`bytebite.container.detect_container` reports the real type. The
member *contents* are irrelevant to detection, so the fixtures stay minimal.
"""

from __future__ import annotations

import zipfile

from bytebite.container import detect_container, read_member_names


def _make_zip(path, members):
    """Write a ZIP at ``path`` whose entries are ``members`` (name -> bytes)."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members:
            zf.writestr(name, data)
    return str(path)


def test_docx_detected(tmp_path):
    p = _make_zip(
        tmp_path / "a.zip",
        [("[Content_Types].xml", b"<x/>"), ("word/document.xml", b"<w/>")],
    )
    kind = detect_container(p)
    assert kind is not None
    assert kind.extension == "docx"


def test_xlsx_detected(tmp_path):
    p = _make_zip(
        tmp_path / "a.zip",
        [("[Content_Types].xml", b"<x/>"), ("xl/workbook.xml", b"<w/>")],
    )
    assert detect_container(p).extension == "xlsx"


def test_pptx_detected(tmp_path):
    p = _make_zip(
        tmp_path / "a.zip",
        [("[Content_Types].xml", b"<x/>"), ("ppt/presentation.xml", b"<p/>")],
    )
    assert detect_container(p).extension == "pptx"


def test_jar_detected(tmp_path):
    p = _make_zip(
        tmp_path / "a.zip",
        [("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\n"), ("Main.class", b"\xca\xfe\xba\xbe")],
    )
    assert detect_container(p).extension == "jar"


def test_apk_detected_before_jar(tmp_path):
    # An APK is also a valid JAR; it must win.
    p = _make_zip(
        tmp_path / "a.zip",
        [
            ("META-INF/MANIFEST.MF", b"Manifest-Version: 1.0\n"),
            ("AndroidManifest.xml", b"\x03\x00\x08\x00"),
            ("classes.dex", b"dex\n035\x00"),
        ],
    )
    assert detect_container(p).extension == "apk"


def test_epub_detected(tmp_path):
    # EPUB convention: first member is an uncompressed 'mimetype'.
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", b"application/epub+zip")
        zf.writestr("META-INF/container.xml", b"<container/>")
        zf.writestr("OEBPS/content.opf", b"<package/>")
    assert detect_container(str(p)).extension == "epub"


def test_odt_detected(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", b"application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", b"<doc/>")
    assert detect_container(str(p)).extension == "odt"


def test_plain_zip_has_no_container(tmp_path):
    p = _make_zip(tmp_path / "a.zip", [("readme.txt", b"hello"), ("data.bin", b"\x00")])
    assert detect_container(p) is None


def test_stdin_and_none_are_ignored():
    assert detect_container(None) is None
    assert detect_container("-") is None
    assert detect_container("<stdin>") is None


def test_non_zip_file_returns_none(tmp_path):
    p = tmp_path / "not.zip"
    p.write_bytes(b"\x89PNG\r\n\x1a\n not a zip at all")
    assert detect_container(str(p)) is None
    assert read_member_names(str(p)) is None


def test_missing_file_returns_none(tmp_path):
    assert detect_container(str(tmp_path / "nope.zip")) is None


def test_read_member_names_respects_limit(tmp_path):
    p = _make_zip(tmp_path / "a.zip", [(f"f{i}.txt", b"x") for i in range(10)])
    names = read_member_names(str(p), limit=3)
    assert names is not None
    assert len(names) == 3
