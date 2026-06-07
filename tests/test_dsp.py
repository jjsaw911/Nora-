import numpy as np
import pytest

from nora_nxdn.dsp import (
    Demodulator,
    dibit_to_level,
    fm_discriminator,
    matched_filter,
    rrc_taps,
    slice_symbols,
)
from nora_nxdn.framing import SyncType, encode_sync_symbols, find_sync
from nora_nxdn.lich import decode_lich, encode_lich_dibits
from nora_nxdn.scramble import pn95_scramble_dibits


def synth_iq(levels, sps, *, beta=0.2, scale=0.2, noise=0.0, seed=0):
    """Synthesize narrowband 4FSK FM IQ from symbol deviation levels."""
    taps = rrc_taps(sps, beta=beta)
    ups = np.zeros(len(levels) * sps)
    ups[::sps] = levels
    freq = np.convolve(ups, taps, mode="same")  # TX pulse shaping
    phase = np.cumsum(freq) * scale
    iq = np.exp(1j * phase)
    if noise:
        rng = np.random.default_rng(seed)
        iq = iq + noise * (rng.standard_normal(iq.size) + 1j * rng.standard_normal(iq.size))
    return iq


def signs(levels):
    return "".join("1" if v > 0 else "3" for v in levels)


def test_rrc_taps_normalized_and_odd():
    t = rrc_taps(10.0)
    assert len(t) % 2 == 1
    assert np.isclose(np.sum(t ** 2), 1.0, atol=1e-6)


def test_discriminator_recovers_frequency():
    # Constant tone -> constant instantaneous frequency.
    n = 200
    f = 0.1
    iq = np.exp(1j * 2 * np.pi * f * np.arange(n))
    disc = fm_discriminator(iq)
    assert np.allclose(disc[1:], 2 * np.pi * f, atol=1e-6)


def test_chain_recovers_symbol_signs_no_timing_loop():
    # Low-level: discriminator + matched filter, sampled on the known grid.
    sps = 10
    guard = [3.0, -3.0] * 4
    payload = [dibit_to_level(d) for d in [3, 1, 2, 0, 3, 3, 1, 0, 2, 1, 3, 0]]
    levels = guard + payload + guard
    iq = synth_iq(levels, sps)
    taps = rrc_taps(sps)
    mf = matched_filter(fm_discriminator(iq), taps)
    centers = mf[:: sps][: len(levels)]
    # Compare interior symbols (skip the first/last guard, edge transients).
    rec = signs(centers)
    exp = signs(levels)
    interior = slice(len(guard), len(guard) + len(payload))
    assert rec[interior] == exp[interior]


def test_full_demod_finds_sync_with_timing_recovery():
    sps = 10
    preamble = [3.0, -3.0] * 12  # dotting for the clock to lock onto
    sync = encode_sync_symbols(SyncType.BS_VOICE)
    tail = [0.0] * 10
    levels = preamble + sync + tail
    iq = synth_iq(levels, sps, noise=0.01)
    demod = Demodulator(sample_rate=sps * 4800.0, symbol_rate=4800.0)
    syms = demod.soft_symbols(iq)
    m = find_sync(syms, max_errors=1)
    assert m is not None
    assert m.sync_type is SyncType.BS_VOICE
    assert not m.inverted


def test_end_to_end_sync_then_lich():
    sps = 10
    code = 0x36  # voice in both half-slots
    lich_dibits = encode_lich_dibits(code)
    scrambled = pn95_scramble_dibits(lich_dibits)
    preamble = [3.0, -3.0] * 12
    sync = encode_sync_symbols(SyncType.BS_VOICE)
    lich_levels = [dibit_to_level(d) for d in scrambled]
    levels = preamble + sync + lich_levels + [0.0] * 12
    iq = synth_iq(levels, sps, noise=0.01)

    demod = Demodulator(sample_rate=sps * 4800.0, symbol_rate=4800.0)
    syms = demod.soft_symbols(iq)
    m = find_sync(syms, max_errors=1)
    assert m is not None and m.sync_type is SyncType.BS_VOICE

    start = m.position + 18
    lich_syms = syms[start : start + 8]
    raw = slice_symbols(lich_syms)
    from nora_nxdn.scramble import pn95_descramble_dibits

    info = decode_lich(pn95_descramble_dibits(raw))
    assert info.code == code
    assert info.parity_ok
    assert info.voice == 3


def test_slice_symbols_handles_empty():
    assert slice_symbols([]) == []
