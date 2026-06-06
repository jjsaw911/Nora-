"""Unit tests for the DSP chain. Run: pytest pi-server/tests/test_dsp.py"""

import numpy as np
import pytest

from app.dsp import (
    AUDIO_RATE,
    FractionalResampler,
    Spectrum,
    make_demodulator,
)
from app.sdr import MockSource


def test_resampler_rate_and_continuity():
    rs = FractionalResampler(256000, AUDIO_RATE, cutoff=11000)
    total = 0
    n_in = 256000 // 25  # ~40 ms blocks
    for _ in range(25):  # ~1 s of input
        out = rs(np.ones(n_in, dtype=np.float64))
        total += len(out)
    # ~1 s -> ~AUDIO_RATE samples, within a few percent.
    assert abs(total - AUDIO_RATE) < AUDIO_RATE * 0.02


@pytest.mark.parametrize("mode", ["wbfm", "nbfm", "am"])
def test_demod_produces_audio(mode):
    src = MockSource(sample_rate=2_048_000)
    demod = make_demodulator(mode, src.sample_rate, squelch_db=-120.0)
    block = int(src.sample_rate * 0.04)
    out = np.concatenate([demod.process(src.read(block)) for _ in range(5)])
    assert out.dtype == np.float32
    assert len(out) > 0
    assert np.all(np.isfinite(out))
    # Bounded (the PCM stage clips to [-1,1]); NBFM/AM may exceed 1.0 on the
    # mock's wideband test signal, but must not blow up.
    assert np.max(np.abs(out)) <= 3.0


def test_wbfm_recovers_tone():
    """The mock source FM-modulates a 440 Hz tone; WBFM should recover it."""
    src = MockSource(sample_rate=2_048_000)
    demod = make_demodulator("wbfm", src.sample_rate, squelch_db=-120.0)
    block = int(src.sample_rate * 0.04)
    chunks = [demod.process(src.read(block)) for _ in range(20)]
    audio = np.concatenate(chunks)[AUDIO_RATE // 10 :]  # skip warmup
    spec = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    freqs = np.fft.rfftfreq(len(audio), 1 / AUDIO_RATE)
    peak = freqs[np.argmax(spec)]
    assert abs(peak - 440) < 20  # dominant tone near 440 Hz


def test_spectrum_frame_shape():
    sp = Spectrum()
    frame = sp.compute(np.zeros(4096, dtype=np.complex64))
    assert isinstance(frame, bytes)
    assert len(frame) == Spectrum.BINS
