"""DSP front end: complex IQ -> 4FSK symbols.

The chain is the usual one for narrowband 4FSK / C4FM:

    IQ -> FM discriminator -> matched (RRC/Gaussian) filter
       -> Gardner symbol-clock recovery -> 4-level slicer -> dibits

NXDN comes in two flavours: 6.25 kHz channels at 2400 baud (4800 bps) and
12.5 kHz channels at 4800 baud (9600 bps). Set :class:`Demodulator` up with the
matching ``symbol_rate``.

The 4-level slicer follows DSD's region convention (see
``nora_nxdn/dsp.py:slice_dibit``): ascending deviation maps to dibits
``1, 0, 2, 3`` so that the dibit MSB equals the sign of the deviation — which is
exactly what :mod:`nora_nxdn.framing` relies on for sign-only sync correlation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

import numpy as np

# Nominal deviation levels (arbitrary units) for the four 4FSK symbols, in the
# order dibit 0,1,2,3 -> level. Chosen so dibit MSB == sign(level).
_DIBIT_TO_LEVEL = {0: -1.0, 1: -3.0, 2: 1.0, 3: 3.0}
_LEVEL_TO_DIBIT_ASC = [1, 0, 2, 3]  # by ascending level: -3,-1,+1,+3


def dibit_to_level(dibit: int) -> float:
    """Map a dibit (0..3) to its nominal 4FSK deviation level."""
    return _DIBIT_TO_LEVEL[dibit]


def slice_dibit(sample: float, center: float, umid: float, lmid: float) -> int:
    """Slice one matched-filter sample into a dibit using DSD's regions.

    ``umid``/``lmid`` are the mid-points between the inner and outer levels.
    """
    if sample > center:
        return 3 if sample > umid else 2
    return 1 if sample < lmid else 0


def fm_discriminator(iq: np.ndarray) -> np.ndarray:
    """Instantaneous-frequency FM demod via the phase-difference method.

    Returns one real sample per input sample (the first is repeated so the
    output length matches the input). Output is proportional to deviation.
    """
    iq = np.asarray(iq, dtype=np.complex128)
    if iq.size < 2:
        return np.zeros(iq.size, dtype=np.float64)
    prod = iq[1:] * np.conj(iq[:-1])
    disc = np.angle(prod)
    return np.concatenate(([disc[0]], disc))


def rrc_taps(sps: float, span: int = 8, beta: float = 0.2) -> np.ndarray:
    """Root-raised-cosine matched-filter taps for ``sps`` samples/symbol."""
    n = int(round(span * sps))
    if n % 2 == 0:
        n += 1  # make it odd for a symmetric, integer-delay filter
    t = (np.arange(n) - (n - 1) / 2.0) / sps
    taps = np.empty(n, dtype=np.float64)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            taps[i] = 1.0 - beta + 4 * beta / np.pi
        elif beta > 0 and abs(abs(4 * beta * ti) - 1.0) < 1e-8:
            taps[i] = (beta / np.sqrt(2)) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta))
            )
        else:
            num = np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(
                np.pi * ti * (1 + beta)
            )
            den = np.pi * ti * (1 - (4 * beta * ti) ** 2)
            taps[i] = num / den
    taps /= np.sqrt(np.sum(taps ** 2))
    return taps


def matched_filter(x: np.ndarray, taps: np.ndarray) -> np.ndarray:
    """Apply a (centred) FIR matched filter, preserving length and delay."""
    return np.convolve(x, taps, mode="same")


def gardner_timing_recovery(
    x: np.ndarray, sps: float, *, loop_bw: float = 0.01
) -> Tuple[np.ndarray, List[float]]:
    """Recover symbols from an oversampled baseband with a Gardner TED.

    Returns ``(symbols, sample_indices)``. The Gardner detector needs a sample
    at each symbol instant and a "midpoint" sample half a symbol earlier, so it
    works directly on the real matched-filter output (no decision needed).
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n < 2 * sps:
        return np.array([]), []

    # Second-order loop gains for a critically-ish damped PLL.
    damping = 1.0 / np.sqrt(2.0)
    theta = loop_bw / (damping + 1.0 / (4.0 * damping))
    denom = 1.0 + 2.0 * damping * theta + theta * theta
    k1 = (4.0 * damping * theta) / denom
    k2 = (4.0 * theta * theta) / denom

    mu = 0.0  # fractional offset within a symbol
    period = sps  # estimated samples/symbol (adapts via the loop)
    base = sps  # nominal
    idx = sps  # current symbol-centre sample position (start a symbol in)
    symbols: List[float] = []
    positions: List[float] = []

    def interp(pos: float) -> float:
        i = int(np.floor(pos))
        frac = pos - i
        if i < 0:
            return x[0]
        if i >= n - 1:
            return x[-1]
        return x[i] * (1 - frac) + x[i + 1] * frac

    while idx < n - 1:
        cur = interp(idx)
        mid = interp(idx - period / 2.0)
        prev = interp(idx - period)
        symbols.append(cur)
        positions.append(idx)
        # Gardner error: mid * (prev - cur). Zero at the correct timing phase.
        err = mid * (prev - cur)
        mu += k1 * err
        period = base + k2 * err * base  # gentle period trim
        idx += period + mu
        mu *= 0.0  # mu folded into idx; keep loop first-order on phase
    return np.asarray(symbols), positions


def estimate_levels(symbols: Sequence[float]) -> Tuple[float, float, float]:
    """Estimate (center, umid, lmid) thresholds from a block of symbols.

    Mirrors DSD's approach: center ~ mean, and the inner mid-points sit 5/8 of
    the way from center toward the extremes.
    """
    s = np.asarray(symbols, dtype=np.float64)
    if s.size == 0:
        return 0.0, 0.0, 0.0
    center = float(np.mean(s))
    hi = float(np.mean(np.sort(s)[-max(1, s.size // 8):]))
    lo = float(np.mean(np.sort(s)[: max(1, s.size // 8)]))
    umid = (hi - center) * 5.0 / 8.0 + center
    lmid = (lo - center) * 5.0 / 8.0 + center
    return center, umid, lmid


def slice_symbols(symbols: Sequence[float]) -> List[int]:
    """Slice a block of matched-filter symbols into dibits."""
    center, umid, lmid = estimate_levels(symbols)
    return [slice_dibit(s, center, umid, lmid) for s in symbols]


@dataclass
class Demodulator:
    """End-to-end IQ -> dibits demodulator.

    Args:
        sample_rate: input IQ sample rate (Hz).
        symbol_rate: NXDN symbol rate (2400 or 4800 baud).
        rrc_beta: matched-filter roll-off.
    """

    sample_rate: float
    symbol_rate: float = 4800.0
    rrc_beta: float = 0.2
    _taps: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.symbol_rate <= 0:
            raise ValueError("sample_rate and symbol_rate must be positive")
        self._taps = rrc_taps(self.sps, beta=self.rrc_beta)

    @property
    def sps(self) -> float:
        return self.sample_rate / self.symbol_rate

    def soft_symbols(self, iq: np.ndarray) -> np.ndarray:
        """IQ -> matched-filtered, timing-recovered soft symbols."""
        disc = fm_discriminator(iq)
        mf = matched_filter(disc, self._taps)
        syms, _ = gardner_timing_recovery(mf, self.sps)
        return syms

    def dibits(self, iq: np.ndarray) -> List[int]:
        """IQ -> hard dibits."""
        return slice_symbols(self.soft_symbols(iq))
