"""nx3000 — read-only codeplug backup tool for the Kenwood NX-3000 series.

Phase 1 scope: discover and document the serial *read* protocol of the
NX-3320K3 and pull its codeplug out as a verified, byte-reproducible binary
blob. **No write/erase commands are ever sent to the radio.** See CLAUDE.md.
"""

__version__ = "0.1.0"
