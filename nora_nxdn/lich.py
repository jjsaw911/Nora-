"""NXDN LICH (Link Information Channel) decoding.

The LICH is carried in the 8 dibits immediately following the frame sync. Each
dibit contributes one information bit (its MSB); the LSB is a fixed "off" bit
that should read 1 on a clean signal and is used as a confidence check. The 8
information bits form a byte whose layout is::

    bit7 .. bit1  : 7-bit LICH code (RF channel type / functional channel / opts)
    bit0          : even parity over bits 7,6,5,4

The 7-bit code is looked up in a table (mirrored from DSD-FME's
``nxdn_frame.c``) to classify the burst: which half-slots carry voice, FACCH,
SACCH, CAC, etc., and whether the burst is outbound (BS) or inbound (MS).

This module assumes the dibits have already been PN95-descrambled
(see :mod:`nora_nxdn.scramble`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

LICH_DIBITS = 8


@dataclass(frozen=True)
class LichInfo:
    """Decoded LICH contents."""

    code: int  # 7-bit LICH code
    raw: int  # full 8-bit value (code << 1 | parity)
    parity_ok: bool
    off_bits: int  # count of LSB "off" bits seen as 1 (8 == perfect)
    inbound: bool  # True if this is an inbound/simplex (MS) burst
    voice: int  # bitfield: half-slot 1 (=1) and/or 2 (=2) carry voice
    facch: int  # bitfield over half-slots carrying FACCH
    sacch: bool
    cac: bool  # control/CAC burst
    description: str


# 7-bit LICH code -> classification. Derived from DSD-FME nxdn_frame.c
# (Type-C / common codes). voice/facch are half-slot bitfields (1, 2, or 3).
@dataclass(frozen=True)
class _Class:
    voice: int = 0
    facch: int = 0
    sacch: bool = False
    cac: bool = False
    desc: str = ""


_LICH_TABLE: Dict[int, _Class] = {
    0x01: _Class(cac=True, desc="CAC (control)"),
    0x05: _Class(cac=True, desc="CAC (control)"),
    0x20: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x21: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x30: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x31: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x40: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x41: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x50: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x51: _Class(facch=3, sacch=True, desc="FACCH in both half-slots"),
    0x32: _Class(voice=2, facch=1, sacch=True, desc="FACCH1/Voice2 (steal)"),
    0x33: _Class(voice=2, facch=1, sacch=True, desc="FACCH1/Voice2 (steal)"),
    0x52: _Class(voice=2, facch=1, sacch=True, desc="FACCH1/Voice2 (steal)"),
    0x53: _Class(voice=2, facch=1, sacch=True, desc="FACCH1/Voice2 (steal)"),
    0x34: _Class(voice=1, facch=2, sacch=True, desc="Voice1/FACCH2 (steal)"),
    0x35: _Class(voice=1, facch=2, sacch=True, desc="Voice1/FACCH2 (steal)"),
    0x54: _Class(voice=1, facch=2, sacch=True, desc="Voice1/FACCH2 (steal)"),
    0x55: _Class(voice=1, facch=2, sacch=True, desc="Voice1/FACCH2 (steal)"),
    0x36: _Class(voice=3, sacch=True, desc="Voice in both half-slots"),
    0x37: _Class(voice=3, sacch=True, desc="Voice in both half-slots"),
    0x56: _Class(voice=3, sacch=True, desc="Voice in both half-slots"),
    0x57: _Class(voice=3, sacch=True, desc="Voice in both half-slots"),
    0x38: _Class(sacch=True, desc="SACCH only (idle/NULL)"),
    0x39: _Class(sacch=True, desc="SACCH only (idle/NULL)"),
}


def _parity_even(code7: int) -> int:
    """Even parity over LICH info bits 7,6,5,4 of the *full* 8-bit value."""
    full = (code7 << 1) & 0xFF
    return ((full >> 7) + (full >> 6) + (full >> 5) + (full >> 4)) & 1


def decode_lich(dibits: Sequence[int]) -> LichInfo:
    """Decode the 8 (descrambled) LICH dibits into a :class:`LichInfo`."""
    if len(dibits) < LICH_DIBITS:
        raise ValueError(f"need {LICH_DIBITS} LICH dibits, got {len(dibits)}")

    info_bits: List[int] = []
    off_bits = 0
    for d in dibits[:LICH_DIBITS]:
        if d < 0 or d > 3:
            raise ValueError(f"dibit out of range: {d!r}")
        info_bits.append((d >> 1) & 1)  # MSB carries LICH info
        off_bits += d & 1  # LSB should be 1 on a clean signal

    full = 0
    for b in info_bits:
        full = (full << 1) | b
    full &= 0xFF

    parity_received = full & 1
    code = full >> 1
    parity_ok = parity_received == _parity_even(code)

    cls = _LICH_TABLE.get(code, _Class(desc=f"unknown LICH code 0x{code:02X}"))
    inbound = (code % 2) == 0  # inbound/simplex bursts have even code

    return LichInfo(
        code=code,
        raw=full,
        parity_ok=parity_ok,
        off_bits=off_bits,
        inbound=inbound,
        voice=cls.voice,
        facch=cls.facch,
        sacch=cls.sacch,
        cac=cls.cac,
        description=cls.desc,
    )


def encode_lich_dibits(code7: int, *, off_fill: bool = True) -> List[int]:
    """Build the 8 LICH dibits for a 7-bit code (for tests/tooling).

    Produces a valid even-parity LSB layout; ``off_fill`` sets the LSB "off"
    bits to 1 as on a real signal.
    """
    full = ((code7 & 0x7F) << 1) | _parity_even(code7 & 0x7F)
    dibits: List[int] = []
    for i in range(LICH_DIBITS):
        msb = (full >> (7 - i)) & 1
        lsb = 1 if off_fill else 0
        dibits.append((msb << 1) | lsb)
    return dibits
