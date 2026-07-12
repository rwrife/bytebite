"""Loading of user-supplied ("custom") signature files.

Every shop has internal binary formats. Rather than forking bytebite to teach
it a proprietary layout, users can drop JSON signature files into a config
directory and bytebite will pick them up at startup — no code change required
(issue #10).

Discovery
---------
By default we scan ``~/.config/bytebite/signatures.d/*.json`` (honouring
``$XDG_CONFIG_HOME`` and a ``$BYTEBITE_SIGNATURES_DIR`` override so tests and
power users can point elsewhere). Each file may contain either a single
signature object or a JSON array of them.

Schema
------
A signature object looks like::

    {
      "name": "ACME blob",
      "category": "database",
      "magic": "hex:41434d45",        # or "ACME" (utf-8) or "base64:..."
      "offset": 0,                     # optional, default 0
      "mask": "hex:ffffffff",          # optional, same length as magic
      "description": "ACME internal record store."
    }

``magic`` and ``mask`` accept three encodings:

* ``"hex:<hexdigits>"`` — raw bytes as hex (whitespace ignored).
* ``"base64:<b64>"``    — raw bytes as base64.
* any other string      — taken as literal UTF-8 text (handy for ASCII magics
  like ``"ACME"``).

Merge semantics
---------------
Custom signatures are appended to the built-ins but *shadow* them: if a custom
signature shares a ``name`` with a built-in, the built-in copies are dropped so
the user's definition wins cleanly (and ``--list-formats`` shows one entry).
Custom signatures never define ``field_layout`` — field decoding is code, not
data — so they contribute magic-byte identification only.

Errors are non-fatal by design: a malformed file is collected into
:class:`LoadReport.errors` and skipped, so one bad drop-in never blocks the
tool. ``bytebite doctor`` surfaces the report.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .signatures import Signature

__all__ = [
    "LoadReport",
    "signatures_dir",
    "load_custom_signatures",
    "decode_bytes_field",
]

_VALID_CATEGORIES = {
    "image",
    "archive",
    "executable",
    "document",
    "audio",
    "database",
    "video",
    "font",
    "data",
    "other",
}


@dataclass
class LoadReport:
    """Outcome of scanning the custom-signatures directory.

    Attributes
    ----------
    directory:
        The directory that was scanned (whether or not it exists).
    signatures:
        Successfully parsed custom signatures, in discovery order.
    errors:
        ``(source, message)`` pairs for anything that could not be loaded. A
        ``source`` is a file path, or a ``"file#index"`` for a bad entry inside
        an otherwise-readable array.
    files_scanned:
        How many ``*.json`` files were found (readable or not).
    """

    directory: Path
    signatures: List[Signature] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    files_scanned: int = 0

    @property
    def ok(self) -> bool:
        """True when nothing failed to load."""
        return not self.errors

    @property
    def count(self) -> int:
        """Number of custom signatures successfully loaded."""
        return len(self.signatures)


def signatures_dir() -> Path:
    """Return the directory bytebite scans for custom signature files.

    Resolution order:
      1. ``$BYTEBITE_SIGNATURES_DIR`` (explicit override).
      2. ``$XDG_CONFIG_HOME/bytebite/signatures.d``.
      3. ``~/.config/bytebite/signatures.d``.
    """
    override = os.environ.get("BYTEBITE_SIGNATURES_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "bytebite" / "signatures.d"


def decode_bytes_field(spec: str) -> bytes:
    """Decode a ``magic``/``mask`` string into raw bytes.

    Supports ``hex:``/``base64:`` prefixes; anything else is literal UTF-8.
    Raises :class:`ValueError` with a clear message on malformed input.
    """
    if not isinstance(spec, str):
        raise ValueError("must be a string")
    if spec.startswith("hex:"):
        raw = spec[4:].replace(" ", "").replace("_", "")
        try:
            return bytes.fromhex(raw)
        except ValueError as exc:
            raise ValueError(f"invalid hex: {exc}") from exc
    if spec.startswith("base64:"):
        try:
            return base64.b64decode(spec[7:], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid base64: {exc}") from exc
    return spec.encode("utf-8")


def _signature_from_obj(obj: dict) -> Signature:
    """Build a :class:`Signature` from a decoded JSON object.

    Raises :class:`ValueError` (or :class:`KeyError` wrapped as one) describing
    the first problem found. Validation mirrors :class:`Signature`'s own rules
    plus a small allow-list of categories and a rejection of ``field_layout``
    (field decoding is built-in code, not user data).
    """
    if not isinstance(obj, dict):
        raise ValueError("signature must be a JSON object")

    for required in ("name", "category", "magic"):
        if required not in obj:
            raise ValueError(f"missing required key {required!r}")

    name = obj["name"]
    category = obj["category"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' must be a non-empty string")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("'category' must be a non-empty string")
    if category not in _VALID_CATEGORIES:
        allowed = ", ".join(sorted(_VALID_CATEGORIES))
        raise ValueError(
            f"unknown category {category!r} (expected one of: {allowed})"
        )

    if "field_layout" in obj:
        raise ValueError(
            "'field_layout' is not allowed in custom signatures "
            "(field decoding is built-in only)"
        )

    magic = decode_bytes_field(obj["magic"])
    if not magic:
        raise ValueError("'magic' decodes to zero bytes")

    mask: Optional[bytes] = None
    if obj.get("mask") is not None:
        mask = decode_bytes_field(obj["mask"])
        if len(mask) != len(magic):
            raise ValueError(
                f"'mask' length {len(mask)} != 'magic' length {len(magic)}"
            )

    offset = obj.get("offset", 0)
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise ValueError("'offset' must be an integer")
    if offset < 0:
        raise ValueError("'offset' must be non-negative")

    description = obj.get("description", "")
    if not isinstance(description, str):
        raise ValueError("'description' must be a string")

    # Signature.__post_init__ re-validates, so any edge we missed still raises.
    return Signature(
        name=name,
        category=category,
        magic=magic,
        offset=offset,
        mask=mask,
        description=description,
    )


def _load_one_file(path: Path, report: LoadReport) -> None:
    """Parse a single ``*.json`` file, appending results/errors to ``report``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.errors.append((str(path), f"cannot read: {exc.strerror or exc}"))
        return

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.errors.append((str(path), f"invalid JSON: {exc}"))
        return

    entries = data if isinstance(data, list) else [data]
    for index, entry in enumerate(entries):
        try:
            report.signatures.append(_signature_from_obj(entry))
        except ValueError as exc:
            source = str(path) if not isinstance(data, list) else f"{path}#{index}"
            report.errors.append((source, str(exc)))


def load_custom_signatures(directory: Optional[Path] = None) -> LoadReport:
    """Scan ``directory`` for ``*.json`` signature files and load them.

    ``directory`` defaults to :func:`signatures_dir`. A missing directory is
    not an error — the report simply has zero files/signatures. Files are
    processed in sorted order for deterministic shadowing; each file may hold a
    single signature object or an array of them.
    """
    directory = directory or signatures_dir()
    report = LoadReport(directory=directory)

    if not directory.is_dir():
        return report

    for path in sorted(directory.glob("*.json")):
        report.files_scanned += 1
        _load_one_file(path, report)

    return report
