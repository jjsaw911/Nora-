import pytest

from nora_nxdn.scramble import (
    PN95_MAX_LEN,
    pn95_descramble_dibits,
    pn95_scramble_dibits,
    pn95_sequence,
)


def test_sequence_is_binary_and_correct_length():
    seq = pn95_sequence(60)
    assert len(seq) == 60
    assert set(seq) <= {0, 1}


def test_sequence_deterministic():
    assert pn95_sequence(40) == pn95_sequence(40)


def test_sequence_first_bit_matches_seed_lsb():
    # Seed 0xE4 = ...100, LSB is 0, so the very first PN bit is 0.
    assert pn95_sequence(1)[0] == 0xE4 & 1


def test_length_bounds():
    with pytest.raises(ValueError):
        pn95_sequence(-1)
    with pytest.raises(ValueError):
        pn95_sequence(PN95_MAX_LEN + 1)


def test_descramble_is_self_inverse():
    dibits = [(i * 7) % 4 for i in range(80)]
    once = pn95_scramble_dibits(dibits)
    twice = pn95_descramble_dibits(once)
    assert twice == dibits


def test_only_msb_is_flipped():
    # Where the PN bit is 1, dibit XORs with 0x2 (MSB); LSB never changes.
    dibits = [0] * 60
    seq = pn95_sequence(60)
    out = pn95_scramble_dibits(dibits)
    for o, p in zip(out, seq):
        assert o == (0x2 if p else 0x0)


def test_rejects_bad_dibit():
    with pytest.raises(ValueError):
        pn95_descramble_dibits([0, 1, 4])
