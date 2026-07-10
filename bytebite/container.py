"""Container awareness for bytebite.

Lots of everyday formats are secretly just ZIP archives with a tell-tale set of
member files inside: a ``.docx`` is a ZIP with ``word/document.xml``, a ``.jar``
is a ZIP with ``META-INF/MANIFEST.MF``, an ``.apk`` adds ``AndroidManifest.xml``,
and an ``.epub`` announces itself with a ``mimetype`` member. When bytebite sees
the ZIP magic (``PK\x03\x04``) it is worth peeking one level deeper so we can
say *"ZIP container → looks like a .docx"* instead of stopping at "ZIP archive".

This module is deliberately small and self-contained. It reads member names via
the stdlib :mod:`zipfile` (no third-party deps, in keeping with PLAN.md) and
maps them onto a known-container table. It never extracts data — only the
central directory listing is consulted — so it stays cheap and safe on hostile
input.

Only real files can be inspected: peeking members needs random access to the
central directory at the *end* of the archive, which a streamed stdin blob or a
truncated head buffer does not provide. Callers pass a filesystem path when they
have one; stdin and non-seekable sources simply get ``None`` back (bytebite then
reports the plain "ZIP archive" identification, unchanged).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from typing import List, Optional, Sequence

# How many member names we are willing to scan. The signals we look for live in
# the first handful of entries in practice (OOXML and epub even mandate order),
# so a generous cap keeps us fast on huge archives without missing anything.
MAX_MEMBERS_SCANNED = 2000


@dataclass(frozen=True)
class ContainerKind:
    """A ZIP-based format recognised by its member layout.

    Attributes
    ----------
    name:
        Human-friendly name, e.g. ``"Word document (OOXML)"``.
    extension:
        The conventional file extension without the dot, e.g. ``"docx"``.
    description:
        One-line description echoed into human/JSON output.
    """

    name: str
    extension: str
    description: str


# --- The container table ----------------------------------------------------
#
# Each entry knows how to recognise itself from a set of ZIP member names. The
# order matters: more specific containers (APK, which is also a valid JAR) are
# checked before their more general lookalikes. Recognition rules are expressed
# as small predicates over the member set so a format can require an exact
# member, a prefix, or a suffix without a rule mini-language.


def _has(members: Sequence[str], name: str) -> bool:
    return name in members


def _has_prefix(members: Sequence[str], prefix: str) -> bool:
    return any(m.startswith(prefix) for m in members)


# Word/Excel/PowerPoint (OOXML) all share ``[Content_Types].xml`` plus a
# format-specific top-level directory. Checking the directory disambiguates the
# three without opening any member.
_DOCX = ContainerKind(
    "Word document (OOXML)", "docx",
    "Office Open XML word processing document (ZIP of word/*.xml).",
)
_XLSX = ContainerKind(
    "Excel spreadsheet (OOXML)", "xlsx",
    "Office Open XML spreadsheet (ZIP of xl/*.xml).",
)
_PPTX = ContainerKind(
    "PowerPoint presentation (OOXML)", "pptx",
    "Office Open XML presentation (ZIP of ppt/*.xml).",
)
_APK = ContainerKind(
    "Android package", "apk",
    "Android application package (ZIP with AndroidManifest.xml + classes.dex).",
)
_JAR = ContainerKind(
    "Java archive", "jar",
    "Java archive (ZIP with META-INF/MANIFEST.MF).",
)
_EPUB = ContainerKind(
    "EPUB book", "epub",
    "EPUB e-book (ZIP whose first member is an uncompressed 'mimetype').",
)
_ODT = ContainerKind(
    "OpenDocument text", "odt",
    "OpenDocument text document (ZIP with a 'mimetype' member).",
)


def _classify(members: Sequence[str]) -> Optional[ContainerKind]:
    """Return the most specific container kind for ``members``, or ``None``.

    ``members`` is the list of archive member names (as :mod:`zipfile` reports
    them). The checks are ordered specific-first so an APK is never mislabelled
    as a plain JAR, and OOXML's shared ``[Content_Types].xml`` is disambiguated
    by the format's top-level directory.
    """
    member_set = set(members)

    # OOXML family — shared marker, disambiguated by the payload directory.
    if _has(member_set, "[Content_Types].xml"):
        if _has_prefix(members, "word/"):
            return _DOCX
        if _has_prefix(members, "xl/"):
            return _XLSX
        if _has_prefix(members, "ppt/"):
            return _PPTX

    # Android before Java: an APK is also a valid JAR, so match it first.
    if _has(member_set, "AndroidManifest.xml") and _has_prefix(members, "classes"):
        return _APK
    if _has(member_set, "AndroidManifest.xml"):
        return _APK

    if _has(member_set, "META-INF/MANIFEST.MF"):
        return _JAR

    # OpenDocument / EPUB both lead with a 'mimetype' member; the mimetype's
    # content tells them apart, but the member name alone is a strong hint.
    if members and members[0] == "mimetype":
        # We only have names here; treat epub/odf by presence of their marker
        # payload directories when available, else report the generic epub-ish
        # container. EPUB carries META-INF/container.xml; ODF carries content.xml.
        if _has(member_set, "META-INF/container.xml"):
            return _EPUB
        if _has(member_set, "content.xml"):
            return _ODT
        return _EPUB
    if _has(member_set, "mimetype"):
        if _has(member_set, "META-INF/container.xml"):
            return _EPUB
        if _has(member_set, "content.xml"):
            return _ODT

    return None


def read_member_names(path: str, limit: int = MAX_MEMBERS_SCANNED) -> Optional[List[str]]:
    """Return up to ``limit`` member names from the ZIP at ``path``.

    Returns ``None`` when ``path`` is not a readable ZIP (bad archive, missing
    central directory, I/O error). Never raises for malformed input — container
    inspection is a best-effort enhancement layered on top of magic-byte
    identification, so a broken archive just yields no container hint.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            names: List[str] = []
            for info in zf.infolist():
                names.append(info.filename)
                if len(names) >= limit:
                    break
            return names
    except (zipfile.BadZipFile, OSError, EOFError, ValueError):
        return None


def detect_container(path: Optional[str]) -> Optional[ContainerKind]:
    """Detect the *real* type of a ZIP-based container at ``path``.

    ``path`` may be ``None`` (or ``"-"``/``"<stdin>"``) when the source is not a
    seekable file; in that case there is no central directory to inspect and the
    function returns ``None``. Otherwise it reads the member names and maps them
    onto the known-container table, returning the best :class:`ContainerKind` or
    ``None`` when the archive is a plain ZIP with no recognised layout.
    """
    if not path or path in ("-", "<stdin>"):
        return None
    names = read_member_names(path)
    if names is None:
        return None
    return _classify(names)
