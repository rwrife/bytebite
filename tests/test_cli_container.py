"""End-to-end CLI tests for container awareness (issue #8).

Proves ``bytebite <docx>`` and ``bytebite <docx> --json`` surface the real ZIP
container type, while a plain ZIP is reported unchanged.
"""

from __future__ import annotations

import json
import zipfile

from bytebite.cli import main


def _make_docx(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", b"<x/>")
        zf.writestr("word/document.xml", b"<w/>")
    return str(path)


def test_identify_docx_human_output(tmp_path, capsys):
    p = _make_docx(tmp_path / "doc.docx")
    code = main([p])
    out = capsys.readouterr().out
    assert code == 0
    assert "ZIP archive" in out
    assert "ZIP container" in out
    assert ".docx" in out


def test_identify_docx_json_output(tmp_path, capsys):
    p = _make_docx(tmp_path / "doc.docx")
    code = main([p, "--json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["match"]["name"] == "ZIP archive"
    assert payload["match"]["container"]["extension"] == "docx"


def test_plain_zip_has_null_container_json(tmp_path, capsys):
    p = tmp_path / "plain.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("readme.txt", b"hello")
    code = main([str(p), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["match"]["name"] == "ZIP archive"
    assert payload["match"]["container"] is None


def test_peek_docx_json_carries_container(tmp_path, capsys):
    p = _make_docx(tmp_path / "doc.docx")
    code = main(["peek", str(p), "--json"])
    out = capsys.readouterr().out
    assert code == 0
    payload = json.loads(out)
    assert payload["match"]["container"]["extension"] == "docx"
