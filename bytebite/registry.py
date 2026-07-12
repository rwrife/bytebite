"""The effective signature registry: built-ins merged with user customs.

:mod:`bytebite.signatures` stays a pure, dependency-free *data* module (the
built-in fingerprints). :mod:`bytebite.custom` knows how to *load* user JSON
drop-ins. This module is the thin seam that combines them so the rest of the
tool has one place to ask "what signatures do we know?" (issue #10).

Merge semantics (see :mod:`bytebite.custom`): custom signatures shadow built-ins
by ``name`` — if the user defines a ``name`` that already exists, the built-in
copies are dropped and the user's win. The result is cached after first use so
we only touch the filesystem once per process; :func:`reset_cache` clears it
(used by tests).
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .custom import LoadReport, load_custom_signatures
from .signatures import SIGNATURES, Signature

_cache: Optional[List[Signature]] = None
_report: Optional[LoadReport] = None


def _merge(builtins: Sequence[Signature], report: LoadReport) -> List[Signature]:
    """Combine built-ins with custom signatures, letting customs shadow by name."""
    shadowed = {sig.name for sig in report.signatures}
    merged: List[Signature] = [s for s in builtins if s.name not in shadowed]
    merged.extend(report.signatures)
    return merged


def _ensure_loaded() -> None:
    global _cache, _report
    if _cache is None:
        _report = load_custom_signatures()
        _cache = _merge(SIGNATURES, _report)


def effective_signatures() -> Sequence[Signature]:
    """Return every signature bytebite knows (built-in + custom), cached."""
    _ensure_loaded()
    assert _cache is not None
    return tuple(_cache)


def custom_report() -> LoadReport:
    """Return the load report for custom signatures (for ``doctor``)."""
    _ensure_loaded()
    assert _report is not None
    return _report


def reset_cache() -> None:
    """Drop the cached registry so the next call re-scans the config dir.

    Intended for tests that manipulate ``$BYTEBITE_SIGNATURES_DIR`` between
    scenarios; not needed in normal single-shot CLI runs.
    """
    global _cache, _report
    _cache = None
    _report = None
