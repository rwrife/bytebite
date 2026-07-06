"""Unit tests for the M5 JSON / quiet helpers in :mod:`bytebite.render`.

These pin the machine-readable contract at the function level (independent of
the CLI): the schema shape, the versioning field, ``--quiet`` line content, and
that :func:`to_json` round-trips to the same dict.
"""

from __future__ import annotations

import json

from bytebite import render
from bytebite.identify import identify
from bytebite.render import SCHEMA_VERSION, quiet_line, result_dict, to_json

PNG_HEAD = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d"
UNKNOWN = b"nothing recognisable in these bytes"


def _best(head: bytes):
    matches = identify(head)
    return matches[0] if matches else None


def test_result_dict_identified_shape() -> None:
    payload = result_dict(_best(PNG_HEAD), source="pic.png")
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["tool"] == "bytebite"
    assert payload["source"] == "pic.png"
    assert payload["identified"] is True
    match = payload["match"]
    assert match["name"] == "PNG image"
    assert match["category"] == "image"
    assert 0.0 < match["confidence"] <= 1.0
    assert match["offset"] == 0
    assert match["end"] == 8
    assert isinstance(match["magic"], str) and match["magic"]


def test_result_dict_unknown_shape() -> None:
    payload = result_dict(_best(UNKNOWN), source="<stdin>")
    assert payload["identified"] is False
    assert payload["match"] is None
    assert payload["source"] == "<stdin>"
    assert payload["schema_version"] == SCHEMA_VERSION


def test_result_dict_source_defaults_to_none() -> None:
    payload = result_dict(_best(PNG_HEAD))
    assert payload["source"] is None


def test_to_json_is_single_line_and_roundtrips() -> None:
    payload = result_dict(_best(PNG_HEAD), source="pic.png")
    line = to_json(payload)
    assert "\n" not in line  # exactly one line; CLI adds the trailing newline
    assert json.loads(line) == payload


def test_to_json_preserves_key_order() -> None:
    line = to_json(result_dict(_best(PNG_HEAD), source="pic.png"))
    # schema_version must lead so consumers can sniff/pin the contract first.
    assert line.startswith('{"schema_version":')


def test_quiet_line_identified_is_just_name() -> None:
    assert quiet_line(_best(PNG_HEAD)) == "PNG image"


def test_quiet_line_unknown_is_empty() -> None:
    assert quiet_line(_best(UNKNOWN)) == ""


def test_schema_version_is_positive_int() -> None:
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1


def test_render_exposes_json_helpers() -> None:
    # Guard the public surface the CLI imports.
    for name in ("result_dict", "to_json", "quiet_line", "SCHEMA_VERSION"):
        assert hasattr(render, name)
