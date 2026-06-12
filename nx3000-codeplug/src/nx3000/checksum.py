"""Candidate block-integrity algorithms and a solver to identify the real one.

The NX-3000's per-block integrity algorithm is UNCONFIRMED (see
``docs/protocol.md`` §5). Prior art says Kenwood TK radios commonly use a plain
8-bit modular sum, but the NXDN-generation NX series may use a CRC-16. Rather than
guess, we implement the likely candidates and a :func:`solve` search that, given a
captured ``(data, expected_checksum)`` pair, reports which algorithm reproduces it.

The CRC search is intentionally dependency-light: if ``crccheck`` is installed it
expands the catalogue, otherwise we fall back to a handful of common CRC-16/8
parameterisations implemented inline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# Simple summing checksums (1 byte out).
# ---------------------------------------------------------------------------


def sum8(data: bytes) -> int:
    """8-bit modular sum (Kenwood TK prior-art favourite)."""
    return sum(data) & 0xFF


def twos_complement_sum8(data: bytes) -> int:
    """Two's-complement of the 8-bit sum (block + checksum sums to 0)."""
    return (-sum(data)) & 0xFF


def xor8(data: bytes) -> int:
    """XOR of all bytes."""
    acc = 0
    for b in data:
        acc ^= b
    return acc & 0xFF


# ---------------------------------------------------------------------------
# CRC-16 (and CRC-8) — minimal inline implementations of common params.
# Each entry: name -> (callable returning int).  Width inferred from the value.
# ---------------------------------------------------------------------------


def _crc16(data: bytes, poly: int, init: int, refin: bool, refout: bool, xorout: int) -> int:
    def _reflect(value: int, width: int) -> int:
        out = 0
        for i in range(width):
            if value & (1 << i):
                out |= 1 << (width - 1 - i)
        return out

    crc = init
    for byte in data:
        b = _reflect(byte, 8) if refin else byte
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    if refout:
        crc = _reflect(crc, 16)
    return (crc ^ xorout) & 0xFFFF


# Common CRC-16 parameterisations worth trying first.
_CRC16_PARAMS: dict[str, tuple[int, int, bool, bool, int]] = {
    # name: (poly, init, refin, refout, xorout)
    "CRC-16/CCITT-FALSE": (0x1021, 0xFFFF, False, False, 0x0000),
    "CRC-16/XMODEM": (0x1021, 0x0000, False, False, 0x0000),
    "CRC-16/KERMIT": (0x1021, 0x0000, True, True, 0x0000),
    "CRC-16/ARC": (0x8005, 0x0000, True, True, 0x0000),
    "CRC-16/MODBUS": (0x8005, 0xFFFF, True, True, 0x0000),
    "CRC-16/USB": (0x8005, 0xFFFF, True, True, 0xFFFF),
}


def crc16(name: str, data: bytes) -> int:
    poly, init, refin, refout, xorout = _CRC16_PARAMS[name]
    return _crc16(data, poly, init, refin, refout, xorout)


# A registry of named candidate algorithms -> callable. 1-byte ones return 0..255,
# CRC-16 ones return 0..65535. The solver matches against whatever width the
# captured expected value implies.
def _candidate_registry() -> dict[str, Callable[[bytes], int]]:
    reg: dict[str, Callable[[bytes], int]] = {
        "sum8": sum8,
        "twos_complement_sum8": twos_complement_sum8,
        "xor8": xor8,
    }
    for name in _CRC16_PARAMS:
        reg[name] = lambda data, _n=name: crc16(_n, data)
    return reg


CANDIDATES = _candidate_registry()


@dataclass(frozen=True)
class SolveResult:
    algorithm: str
    value: int
    width_bits: int


def solve(
    data: bytes,
    expected: int,
    *,
    extra: dict[str, Callable[[bytes], int]] | None = None,
) -> list[SolveResult]:
    """Return every candidate algorithm that reproduces ``expected`` over ``data``.

    Pass several ``(data, expected)`` pairs through :func:`solve_many` to narrow
    to a single algorithm — one block can have coincidental matches.
    """
    registry = dict(CANDIDATES)
    if extra:
        registry.update(extra)

    hits: list[SolveResult] = []
    for name, fn in registry.items():
        got = fn(data)
        if got == expected:
            width = 16 if got > 0xFF or expected > 0xFF else 8
            hits.append(SolveResult(name, got, width))
    return hits


def solve_many(
    samples: list[tuple[bytes, int]],
    *,
    extra: dict[str, Callable[[bytes], int]] | None = None,
) -> list[str]:
    """Return algorithm names that match **every** ``(data, expected)`` sample.

    This is the real discriminator: feed it block+checksum pairs from a capture
    and it collapses to the one true algorithm (ideally exactly one name).
    """
    if not samples:
        return []
    common: set[str] | None = None
    for data, expected in samples:
        names = {r.algorithm for r in solve(data, expected, extra=extra)}
        common = names if common is None else (common & names)
    return sorted(common or set())
