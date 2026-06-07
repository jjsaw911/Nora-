import pytest

from nora_nxdn.lich import LICH_DIBITS, decode_lich, encode_lich_dibits


def test_roundtrip_known_codes():
    for code, expect in [
        (0x01, "cac"),
        (0x36, "voice"),
        (0x34, "steal"),
        (0x38, "sacch"),
    ]:
        dibits = encode_lich_dibits(code)
        info = decode_lich(dibits)
        assert info.code == code
        assert info.parity_ok
        assert info.off_bits == LICH_DIBITS  # all off-bits set
        if expect == "cac":
            assert info.cac
        if expect == "voice":
            assert info.voice == 3
        if expect == "steal":
            assert info.voice == 1 and info.facch == 2
        if expect == "sacch":
            assert info.sacch and info.voice == 0


def test_voice_both_halfslots():
    info = decode_lich(encode_lich_dibits(0x37))
    assert info.voice == 3 and info.sacch


def test_facch_both_halfslots():
    info = decode_lich(encode_lich_dibits(0x20))
    assert info.facch == 3 and info.voice == 0


def test_inbound_flag_even_code():
    # 0x36 is even -> inbound/simplex; 0x37 is odd -> outbound.
    assert decode_lich(encode_lich_dibits(0x36)).inbound
    assert not decode_lich(encode_lich_dibits(0x37)).inbound


def test_parity_error_detected():
    dibits = encode_lich_dibits(0x36)
    # Corrupt one info bit (an MSB) without touching the parity dibit.
    dibits[2] ^= 0x2
    info = decode_lich(dibits)
    assert not info.parity_ok


def test_off_bits_count():
    dibits = encode_lich_dibits(0x36, off_fill=True)
    dibits[0] &= ~1  # clear one off-bit
    info = decode_lich(dibits)
    assert info.off_bits == LICH_DIBITS - 1


def test_unknown_code_is_described():
    info = decode_lich(encode_lich_dibits(0x7F))
    assert "unknown" in info.description.lower()


def test_requires_eight_dibits():
    with pytest.raises(ValueError):
        decode_lich([0, 1, 2])
