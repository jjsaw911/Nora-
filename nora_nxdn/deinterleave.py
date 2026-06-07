"""NXDN bit (de)interleaving and the AMBE interleave schedule.

NXDN block-interleaves the convolutionally-coded bits of its logical channels
before transmission. The permutation tables below (``PERM_*``) are the
row/column interleave maps for the various block sizes, mirrored from
DSD-FME / OP25 (``include/nxdn_const.h``). Deinterleaving is just applying the
inverse permutation.

``AMBE_SCHEDULE`` is the NXDN-specific AMBE interleave schedule (the nW/nX/nY/nZ
tables from DSD's ``nxdn_const.h``), used when reassembling AMBE voice frames
before they are handed to an external vocoder.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

# Block interleave maps. Keyed by the (info, total) shape they describe, the way
# DSD-FME names them. Each maps output index -> input (transmit-order) index.
PERM_12_5: List[int] = [
    0, 12, 24, 36, 48, 1, 13, 25, 37, 49, 2, 14, 26, 38, 50,
    3, 15, 27, 39, 51, 4, 16, 28, 40, 52, 5, 17, 29, 41, 53,
    6, 18, 30, 42, 54, 7, 19, 31, 43, 55, 8, 20, 32, 44, 56,
    9, 21, 33, 45, 57, 10, 22, 34, 46, 58, 11, 23, 35, 47, 59,
]

PERM_16_9: List[int] = [
    (r + 16 * c) for r in range(16) for c in range(9)
]

PERM_12_25: List[int] = [
    (r + 12 * c) for r in range(12) for c in range(25)
]

PERM_12_29: List[int] = [
    (r + 12 * c) for r in range(12) for c in range(29)
]

# NXDN AMBE interleave schedule (DSD nxdn_const.h: nW, nX, nY, nZ).
AMBE_W: List[int] = [
    0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
    0, 1, 0, 1, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2,
]
AMBE_X: List[int] = [
    23, 10, 22, 9, 21, 8, 20, 7, 19, 6, 18, 5, 17, 4, 16, 3, 15, 2,
    14, 1, 13, 0, 12, 10, 11, 9, 10, 8, 9, 7, 8, 6, 7, 5, 6, 4,
]
AMBE_Y: List[int] = [
    0, 2, 0, 2, 0, 2, 0, 2, 0, 3, 0, 3, 1, 3, 1, 3, 1, 3,
    1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3,
]
AMBE_Z: List[int] = [
    5, 3, 4, 2, 3, 1, 2, 0, 1, 13, 0, 12, 22, 11, 21, 10, 20, 9,
    19, 8, 18, 7, 17, 6, 16, 5, 15, 4, 14, 3, 13, 2, 12, 1, 11, 0,
]

AMBE_SCHEDULE: Dict[str, List[int]] = {
    "W": AMBE_W,
    "X": AMBE_X,
    "Y": AMBE_Y,
    "Z": AMBE_Z,
}


def _check_permutation(perm: Sequence[int]) -> None:
    if sorted(perm) != list(range(len(perm))):
        raise ValueError("permutation is not a bijection over 0..n-1")


def deinterleave(bits: Sequence[int], perm: Sequence[int]) -> List[int]:
    """Undo a block interleave.

    ``perm[i]`` is the transmit-order index of the i-th deinterleaved bit, so
    ``out[i] = bits[perm[i]]``. ``len(bits)`` must equal ``len(perm)``.
    """
    if len(bits) != len(perm):
        raise ValueError(
            f"length mismatch: {len(bits)} bits vs {len(perm)} permutation"
        )
    return [bits[perm[i]] for i in range(len(perm))]


def interleave(bits: Sequence[int], perm: Sequence[int]) -> List[int]:
    """Apply a block interleave (inverse of :func:`deinterleave`)."""
    if len(bits) != len(perm):
        raise ValueError(
            f"length mismatch: {len(bits)} bits vs {len(perm)} permutation"
        )
    out = [0] * len(perm)
    for i in range(len(perm)):
        out[perm[i]] = bits[i]
    return out


# Validate the tables at import time — cheap insurance against typos.
for _name, _p in (
    ("PERM_12_5", PERM_12_5),
    ("PERM_16_9", PERM_16_9),
    ("PERM_12_25", PERM_12_25),
    ("PERM_12_29", PERM_12_29),
):
    _check_permutation(_p)
