"""bytebite — a pocket detective for mystery files.

Fingerprints unknown binaries by their magic bytes and structural tells, then
serves up an annotated hex peek where the recognized header fields are labeled.

This is the M1 scaffold: only the version and CLI wiring live here so far. The
identification engine, hex peek, and signature registry arrive in later
milestones (see PLAN.md).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
