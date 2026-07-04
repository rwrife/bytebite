"""bytebite — a pocket detective for mystery files.

Fingerprints unknown binaries by their magic bytes and structural tells, then
serves up an annotated hex peek where the recognized header fields are labeled.

M2 adds the core identification engine: the signature registry
(:mod:`bytebite.signatures`) and the matcher (:mod:`bytebite.identify`). The
annotated hex peek and structured JSON output arrive in later milestones
(see PLAN.md).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
