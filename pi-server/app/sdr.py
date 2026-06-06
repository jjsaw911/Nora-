"""SDR sample sources.

Two implementations behind a common interface:

* ``RtlSdrSource`` — real hardware via ``pyrtlsdr`` (librtlsdr).
* ``MockSource`` — synthetic IQ so the whole M1-M3 pipeline (audio + spectrum)
  can be built and tested with no dongle attached. It fabricates a wideband-FM
  carrier modulated by a 440 Hz tone at the tuned center, plus a couple of
  steady pilot carriers offset in the band so the waterfall shows structure.

Both expose blocking ``read(n)`` returning ``complex64`` and property setters
for center frequency / sample rate / gain. The radio runs them in a worker
thread, never on the event loop.
"""

from __future__ import annotations

import logging
import time

import numpy as np

log = logging.getLogger("NetworkedSDR.sdr")


class SdrSource:
    """Interface implemented by both the real and mock sources."""

    sample_rate: float
    center_freq: float
    gain: object  # float dB or "auto"

    def read(self, n: int) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass

    @property
    def is_mock(self) -> bool:
        return False


class RtlSdrSource(SdrSource):
    """Real RTL-SDR via pyrtlsdr."""

    def __init__(self, sample_rate=2_048_000, center_freq=96_900_000, gain="auto"):
        from rtlsdr import RtlSdr  # imported lazily so the mock path needs no lib

        self._sdr = RtlSdr()
        self._sdr.sample_rate = sample_rate
        self._sdr.center_freq = center_freq
        self.set_gain(gain)
        # Reading a small throwaway block flushes the dongle's startup garbage.
        try:
            self._sdr.read_samples(2048)
        except Exception:  # noqa: BLE001
            pass
        log.info("RtlSdr opened: fs=%.0f fc=%.0f gain=%s", sample_rate, center_freq, gain)

    @property
    def sample_rate(self) -> float:
        return float(self._sdr.sample_rate)

    @sample_rate.setter
    def sample_rate(self, value: float) -> None:
        self._sdr.sample_rate = value

    @property
    def center_freq(self) -> float:
        return float(self._sdr.center_freq)

    @center_freq.setter
    def center_freq(self, value: float) -> None:
        self._sdr.center_freq = value

    def set_gain(self, gain) -> None:
        if gain == "auto" or gain is None:
            self._sdr.gain = "auto"
        else:
            self._sdr.gain = float(gain)

    @property
    def gain(self):
        try:
            return float(self._sdr.gain)
        except Exception:  # noqa: BLE001
            return "auto"

    def read(self, n: int) -> np.ndarray:
        return self._sdr.read_samples(n).astype(np.complex64)

    def close(self) -> None:
        try:
            self._sdr.close()
        except Exception:  # noqa: BLE001
            pass


class MockSource(SdrSource):
    """Synthetic IQ generator for hardware-free development."""

    def __init__(self, sample_rate=2_048_000, center_freq=96_900_000, gain="auto"):
        self._fs = float(sample_rate)
        self._fc = float(center_freq)
        self._gain = gain
        self._phase = 0.0          # FM modulator phase accumulator
        self._tone_phase = 0.0     # audio tone phase
        self._t0 = time.time()
        self._rng = np.random.default_rng(1234)
        log.info("MockSource active (no hardware): fs=%.0f fc=%.0f", sample_rate, center_freq)

    @property
    def sample_rate(self) -> float:
        return self._fs

    @sample_rate.setter
    def sample_rate(self, value: float) -> None:
        self._fs = float(value)

    @property
    def center_freq(self) -> float:
        return self._fc

    @center_freq.setter
    def center_freq(self, value: float) -> None:
        self._fc = float(value)

    def set_gain(self, gain) -> None:
        self._gain = gain

    @property
    def gain(self):
        return self._gain

    @property
    def is_mock(self) -> bool:
        return True

    def read(self, n: int) -> np.ndarray:
        # Pace the generator to roughly real time so timing behaves like hardware.
        target_dt = n / self._fs
        elapsed = time.time() - self._t0
        if elapsed < target_dt:
            time.sleep(target_dt - elapsed)
        self._t0 = time.time()

        fs = self._fs
        # --- WBFM carrier at DC (the tuned station): 440 Hz tone, 75 kHz dev ---
        f_audio = 440.0
        deviation = 75_000.0
        t = np.arange(n)
        tone_phase = self._tone_phase + 2 * np.pi * f_audio * t / fs
        msg = np.sin(tone_phase)
        # Integrate message for FM phase.
        inst_phase = self._phase + np.cumsum(2 * np.pi * deviation * msg / fs)
        carrier = 0.5 * np.exp(1j * inst_phase)
        self._phase = float(inst_phase[-1] % (2 * np.pi))
        self._tone_phase = float((self._tone_phase + 2 * np.pi * f_audio * n / fs) % (2 * np.pi))

        # --- a couple of steady offset carriers so the waterfall has features ---
        for off, amp in ((300_000.0, 0.15), (-450_000.0, 0.1)):
            carrier += amp * np.exp(1j * 2 * np.pi * off * t / fs)

        # --- noise floor ---
        noise = (self._rng.standard_normal(n) + 1j * self._rng.standard_normal(n)) * 0.02
        return (carrier + noise).astype(np.complex64)


def open_source(sample_rate, center_freq, gain, force_mock=False) -> SdrSource:
    """Open the real dongle, falling back to the mock source if unavailable."""
    if force_mock:
        return MockSource(sample_rate, center_freq, gain)
    try:
        return RtlSdrSource(sample_rate, center_freq, gain)
    except Exception as exc:  # noqa: BLE001
        log.warning("RTL-SDR unavailable (%s); falling back to MockSource", exc)
        return MockSource(sample_rate, center_freq, gain)
