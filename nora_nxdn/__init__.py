"""Nora NXDN — a clean-room NXDN protocol decoder for macOS + RTL-SDR.

This package decodes the NXDN *protocol* (frame sync, LICH, signalling/control
channels, and voice-frame extraction) from a 4FSK baseband. The DSP front end
(FM discrimination, matched filtering, symbol-clock recovery, 4-level slicing)
lives in :mod:`nora_nxdn.dsp`; the protocol layers live in the remaining
modules.

The protocol constants here (frame sync words, the PN95 dibit scrambler, the
LICH type table, the interleave/permutation tables and the AMBE interleave
schedule) were derived from the open-source DSD / DSD-FME projects, which is the
canonical reference for NXDN decoding. See ``docs/protocol-notes.md`` for the
exact provenance of each constant.

Voice *audio* output is intentionally out of scope: NXDN voice uses the
proprietary AMBE+2 vocoder, so decoded voice frames are handed off to an
external vocoder (mbelib / an AMBE hardware dongle / DSD itself). See
``docs/architecture.md``.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .framing import (
    SyncMatch,
    SyncType,
    find_sync,
    iter_sync,
)
from .lich import LichInfo, decode_lich
from .scramble import pn95_descramble_dibits, pn95_sequence
from .channelmap import ChannelMap

__all__ = [
    "__version__",
    "SyncMatch",
    "SyncType",
    "find_sync",
    "iter_sync",
    "LichInfo",
    "decode_lich",
    "pn95_descramble_dibits",
    "pn95_sequence",
    "ChannelMap",
]
