import numpy as np

from nora_nxdn.framing import (
    SYNC_LEN,
    SyncType,
    encode_sync_symbols,
    find_sync,
    iter_sync,
    symbols_to_sign_string,
)


def test_encode_decode_roundtrip_all_types():
    for st in SyncType:
        for inverted in (False, True):
            syms = encode_sync_symbols(st, inverted=inverted)
            m = find_sync(syms, max_errors=0)
            assert m is not None
            assert m.position == 0
            assert m.sync_type is st
            assert m.inverted is inverted
            assert m.errors == 0


def test_sync_found_with_leading_noise():
    rng = np.random.default_rng(0)
    noise = list(rng.uniform(-3, 3, size=37))
    syms = noise + encode_sync_symbols(SyncType.BS_VOICE) + [0.0] * 10
    m = find_sync(syms, max_errors=0)
    assert m is not None
    assert m.position == 37
    assert m.sync_type is SyncType.BS_VOICE


def test_fuzzy_match_tolerates_one_flip():
    syms = encode_sync_symbols(SyncType.MS_DATA)
    syms[3] = -syms[3]  # flip one symbol's sign
    assert find_sync(syms, max_errors=0) is None
    m = find_sync(syms, max_errors=1)
    assert m is not None and m.sync_type is SyncType.MS_DATA and m.errors == 1


def test_iter_sync_finds_multiple():
    burst = encode_sync_symbols(SyncType.BS_VOICE) + [0.1] * 22
    stream = burst * 3
    matches = list(iter_sync(stream, max_errors=0))
    assert len(matches) == 3
    assert [m.position for m in matches] == [0, 40, 80]


def test_sign_string_convention():
    assert symbols_to_sign_string([3.0, -3.0, 0.5, -0.5]) == "1313"


def test_sync_len_constant():
    assert SYNC_LEN == 18
    assert len(encode_sync_symbols(SyncType.BS_DATA)) == SYNC_LEN
