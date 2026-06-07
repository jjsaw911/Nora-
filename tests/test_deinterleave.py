import pytest

from nora_nxdn.deinterleave import (
    AMBE_SCHEDULE,
    PERM_12_5,
    PERM_12_25,
    PERM_12_29,
    PERM_16_9,
    deinterleave,
    interleave,
)


@pytest.mark.parametrize(
    "perm,n",
    [
        (PERM_12_5, 60),
        (PERM_16_9, 144),
        (PERM_12_25, 300),
        (PERM_12_29, 348),
    ],
)
def test_perm_tables_are_bijections(perm, n):
    assert len(perm) == n
    assert sorted(perm) == list(range(n))


def test_interleave_deinterleave_roundtrip():
    bits = [(i * 5 + 1) % 2 for i in range(60)]
    assert deinterleave(interleave(bits, PERM_12_5), PERM_12_5) == bits


def test_deinterleave_known_mapping():
    # out[i] = bits[perm[i]]; check the first few against PERM_12_5.
    bits = list(range(60))
    out = deinterleave(bits, PERM_12_5)
    assert out[0] == 0
    assert out[1] == 12
    assert out[2] == 24


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        deinterleave([0, 1, 2], PERM_12_5)


def test_ambe_schedule_shapes():
    for key in ("W", "X", "Y", "Z"):
        assert len(AMBE_SCHEDULE[key]) == 36
