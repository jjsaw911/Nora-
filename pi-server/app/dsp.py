"""DSP chain for the Networked SDR server.

Everything here is *stateful and block-based*: the SDR delivers IQ in chunks,
and each demodulator keeps its filter/phase state between chunks so there are no
clicks at block boundaries. Audio is produced as float32 in [-1, 1]; the radio
layer converts that to 16-bit little-endian PCM.

Signal flow (per the project brief):

  WBFM:  IQ --lp+decimate--> ~256 kHz --FM discriminate--> 75us de-emphasis
         --lp+resample--> 24 kHz mono
  NBFM:  IQ --lp+decimate--> 32 kHz (narrow) --FM discriminate--> (squelch)
         --resample--> 24 kHz
  AM:    IQ --lp+decimate--> 32 kHz --envelope (|x|)--> DC removal
         --resample--> 24 kHz
"""

from __future__ import annotations

import numpy as np
from scipy.signal import firwin, lfilter, lfilter_zi

AUDIO_RATE = 24000          # final mono audio sample rate (Hz)
IF_RATE = 256000            # first-stage intermediate frequency rate (Hz)
NARROW_RATE = 32000         # IF rate for NBFM / AM (Hz)
DEEMPHASIS_TAU = 75e-6      # 75 us de-emphasis time constant (region 1 / Americas)


# --------------------------------------------------------------------------- #
# Stateful building blocks
# --------------------------------------------------------------------------- #
class FIRDecimator:
    """Anti-alias lowpass FIR followed by integer decimation, with state.

    Keeps both the filter delay line (``zi``) and the decimation phase across
    calls so consecutive blocks join seamlessly regardless of block length.
    """

    def __init__(self, fs_in: float, factor: int, cutoff: float, numtaps: int = 64):
        self.factor = int(factor)
        self.taps = firwin(numtaps, cutoff, fs=fs_in).astype(np.float64)
        # complex-aware delay line: store separately is unnecessary, lfilter
        # handles complex input as long as zi is complex.
        self._zi = lfilter_zi(self.taps, 1.0) * 0.0
        self._zi = self._zi.astype(np.complex128)
        self.phase = 0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = lfilter(self.taps, 1.0, x, zi=self._zi)
        out = y[self.phase :: self.factor]
        consumed = len(y)
        if self.phase < consumed:
            k = (consumed - self.phase + self.factor - 1) // self.factor
            last_idx = self.phase + (k - 1) * self.factor
            self.phase = last_idx + self.factor - consumed
        else:
            self.phase -= consumed
        return out


class Deemphasis:
    """Single-pole IIR de-emphasis filter (FM broadcast)."""

    def __init__(self, fs: float, tau: float = DEEMPHASIS_TAU):
        # Standard single-pole RC: y[n] = (1-d) x[n] + d y[n-1]
        d = float(np.exp(-1.0 / (fs * tau)))
        self.b = np.array([1.0 - d], dtype=np.float64)
        self.a = np.array([1.0, -d], dtype=np.float64)
        self._zi = lfilter_zi(self.b, self.a) * 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = lfilter(self.b, self.a, x, zi=self._zi)
        return y


class FractionalResampler:
    """Rational/irrational resampler: stateful lowpass + linear interpolation.

    Used for the final stage (e.g. 256000 -> 24000 or 32000 -> 24000) where the
    ratio is not an integer. The lowpass removes images before the linear
    interpolation; state (filter delay + fractional phase + one history sample)
    is carried across blocks for click-free output.
    """

    def __init__(self, fs_in: float, fs_out: float, cutoff: float, numtaps: int = 64):
        self.step = float(fs_in) / float(fs_out)
        self.taps = firwin(numtaps, cutoff, fs=fs_in).astype(np.float64)
        self._zi = lfilter_zi(self.taps, 1.0) * 0.0
        self._prev = 0.0          # last filtered sample of previous block
        self._t = 1.0             # next sample position within extended block

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if len(x) == 0:
            return np.zeros(0, dtype=np.float32)
        y, self._zi = lfilter(self.taps, 1.0, x, zi=self._zi)
        ext = np.concatenate(([self._prev], y))  # ext[0] == previous tail
        n = len(ext)
        # Vectorised linear interpolation at positions t, t+step, ...
        count = int(np.floor((n - 1 - self._t) / self.step)) + 1
        if count <= 0:
            self._prev = y[-1]
            self._t -= (n - 1)
            return np.zeros(0, dtype=np.float32)
        positions = self._t + self.step * np.arange(count)
        idx = np.floor(positions).astype(np.int64)
        frac = positions - idx
        out = ext[idx] * (1.0 - frac) + ext[idx + 1] * frac
        self._prev = y[-1]
        self._t = positions[-1] + self.step - (n - 1)
        return out.astype(np.float32)


# --------------------------------------------------------------------------- #
# Demodulators
# --------------------------------------------------------------------------- #
class Demodulator:
    """Base interface. ``process`` consumes complex64 IQ, returns float32 audio."""

    def process(self, iq: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


def _fm_discriminate(iq: np.ndarray, prev: complex) -> tuple[np.ndarray, complex]:
    """Polar-discriminator FM demod. Returns (audio, new_prev_sample)."""
    if len(iq) == 0:
        return np.zeros(0, dtype=np.float64), prev
    x = np.empty(len(iq) + 1, dtype=np.complex128)
    x[0] = prev
    x[1:] = iq
    demod = np.angle(x[1:] * np.conj(x[:-1]))
    return demod, complex(iq[-1])


class WBFMDemodulator(Demodulator):
    """Wideband FM (broadcast)."""

    def __init__(self, sample_rate: float):
        factor = max(1, int(round(sample_rate / IF_RATE)))
        self.if_rate = sample_rate / factor
        self.decim = FIRDecimator(sample_rate, factor, cutoff=100_000, numtaps=64)
        self._prev = 0j
        self.deemph = Deemphasis(self.if_rate, DEEMPHASIS_TAU)
        self.resamp = FractionalResampler(self.if_rate, AUDIO_RATE, cutoff=11_000)
        self.gain = 1.0 / np.pi  # discriminator output is in radians (~+/- pi)

    def process(self, iq: np.ndarray) -> np.ndarray:
        baseband = self.decim(iq)
        demod, self._prev = _fm_discriminate(baseband, self._prev)
        demod = self.deemph(demod) * self.gain
        return self.resamp(demod)


class NBFMDemodulator(Demodulator):
    """Narrowband FM with power squelch (no de-emphasis)."""

    def __init__(self, sample_rate: float, squelch_db: float = -40.0):
        f1 = max(1, int(round(sample_rate / IF_RATE)))
        self.decim1 = FIRDecimator(sample_rate, f1, cutoff=100_000, numtaps=64)
        if_rate = sample_rate / f1
        f2 = max(1, int(round(if_rate / NARROW_RATE)))
        self.narrow_rate = if_rate / f2
        # ~7 kHz channel half-bandwidth for ~12.5 kHz NBFM
        self.decim2 = FIRDecimator(if_rate, f2, cutoff=7_000, numtaps=64)
        self._prev = 0j
        self.resamp = FractionalResampler(self.narrow_rate, AUDIO_RATE, cutoff=8_000)
        self.squelch_db = squelch_db
        self.gain = 2.0 / np.pi
        self.last_power_db = -120.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        narrow = self.decim2(self.decim1(iq))
        if len(narrow) == 0:
            return np.zeros(0, dtype=np.float32)
        power = float(np.mean(np.abs(narrow) ** 2)) + 1e-12
        self.last_power_db = 10.0 * np.log10(power)
        demod, self._prev = _fm_discriminate(narrow, self._prev)
        audio = self.resamp(demod * self.gain)
        if self.last_power_db < self.squelch_db:
            audio = np.zeros_like(audio)
        return audio


class AMDemodulator(Demodulator):
    """Envelope-detected AM with DC removal and optional squelch."""

    def __init__(self, sample_rate: float, squelch_db: float = -60.0):
        f1 = max(1, int(round(sample_rate / IF_RATE)))
        self.decim1 = FIRDecimator(sample_rate, f1, cutoff=100_000, numtaps=64)
        if_rate = sample_rate / f1
        f2 = max(1, int(round(if_rate / NARROW_RATE)))
        self.narrow_rate = if_rate / f2
        self.decim2 = FIRDecimator(if_rate, f2, cutoff=6_000, numtaps=64)
        self.resamp = FractionalResampler(self.narrow_rate, AUDIO_RATE, cutoff=6_000)
        self.squelch_db = squelch_db
        self._dc = 0.0            # running DC estimate for the envelope
        self._dc_alpha = 0.001
        self.last_power_db = -120.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        narrow = self.decim2(self.decim1(iq))
        if len(narrow) == 0:
            return np.zeros(0, dtype=np.float32)
        power = float(np.mean(np.abs(narrow) ** 2)) + 1e-12
        self.last_power_db = 10.0 * np.log10(power)
        env = np.abs(narrow)
        # Remove DC with a simple leaky integrator (carrier level).
        out = np.empty_like(env)
        dc = self._dc
        a = self._dc_alpha
        for i in range(len(env)):       # short blocks; cheap enough on a Pi
            dc += a * (env[i] - dc)
            out[i] = env[i] - dc
        self._dc = dc
        audio = self.resamp(out * 4.0)
        if self.last_power_db < self.squelch_db:
            audio = np.zeros_like(audio)
        return audio


def make_demodulator(mode: str, sample_rate: float, squelch_db: float) -> Demodulator:
    mode = mode.lower()
    if mode == "wbfm":
        return WBFMDemodulator(sample_rate)
    if mode == "nbfm":
        return NBFMDemodulator(sample_rate, squelch_db)
    if mode == "am":
        return AMDemodulator(sample_rate, squelch_db)
    raise ValueError(f"unknown mode: {mode!r}")


# --------------------------------------------------------------------------- #
# Spectrum
# --------------------------------------------------------------------------- #
class Spectrum:
    """Fixed 1024-bin power spectrum, mapped to uint8 bytes.

    dB-to-byte mapping (documented for the client):
        db   = 20*log10(|FFT| / N)        # dBFS, 0 dBFS == full scale
        db   = clip(db, -100, 0)
        byte = round((db + 100) / 100 * 255)   # -100 dBFS -> 0, 0 dBFS -> 255
    """

    BINS = 1024
    DB_FLOOR = -100.0
    DB_CEIL = 0.0

    def __init__(self) -> None:
        self.window = np.hanning(self.BINS).astype(np.float64)
        # Coherent-gain normalisation so a full-scale tone reads ~0 dBFS.
        self._norm = np.sum(self.window)

    def compute(self, iq: np.ndarray) -> bytes:
        if len(iq) < self.BINS:
            buf = np.zeros(self.BINS, dtype=np.complex128)
            buf[: len(iq)] = iq
            seg = buf
        else:
            seg = iq[-self.BINS :]
        spec = np.fft.fftshift(np.fft.fft(seg * self.window))
        mag = np.abs(spec) / self._norm
        db = 20.0 * np.log10(mag + 1e-12)
        db = np.clip(db, self.DB_FLOOR, self.DB_CEIL)
        byte = ((db - self.DB_FLOOR) / (self.DB_CEIL - self.DB_FLOOR) * 255.0)
        return np.round(byte).astype(np.uint8).tobytes()
