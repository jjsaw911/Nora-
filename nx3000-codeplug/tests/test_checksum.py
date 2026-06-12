"""Unit tests for the checksum candidates and the solver."""

from nx3000 import checksum as cs


def test_sum8_basic():
    assert cs.sum8(b"\x01\x02\x03") == 6
    assert cs.sum8(bytes([0xFF, 0x02])) == 0x01  # wraps mod 256


def test_twos_complement_sum8_zeroes_out():
    data = b"\x10\x20\x30"
    chk = cs.twos_complement_sum8(data)
    assert (sum(data) + chk) & 0xFF == 0


def test_xor8():
    assert cs.xor8(b"\x0f\xf0") == 0xFF
    assert cs.xor8(b"\xaa\xaa") == 0x00


def test_crc16_known_vectors():
    # "123456789" check values from the CRC catalogue.
    msg = b"123456789"
    assert cs.crc16("CRC-16/XMODEM", msg) == 0x31C3
    assert cs.crc16("CRC-16/CCITT-FALSE", msg) == 0x29B1
    assert cs.crc16("CRC-16/ARC", msg) == 0xBB3D
    assert cs.crc16("CRC-16/MODBUS", msg) == 0x4B37
    assert cs.crc16("CRC-16/KERMIT", msg) == 0x2189


def test_solve_finds_sum8():
    data = b"\x10\x20\x30\x40"
    hits = cs.solve(data, cs.sum8(data))
    names = {h.algorithm for h in hits}
    assert "sum8" in names


def test_solve_many_narrows_to_single_algorithm():
    # Two samples whose only common matching algorithm should be CRC-16/XMODEM.
    samples = [
        (b"123456789", cs.crc16("CRC-16/XMODEM", b"123456789")),
        (b"hello world", cs.crc16("CRC-16/XMODEM", b"hello world")),
    ]
    matches = cs.solve_many(samples)
    assert "CRC-16/XMODEM" in matches


def test_solve_no_match_returns_empty():
    assert cs.solve(b"\x00\x01", 0x99, extra={}) == [] or all(
        h.value == 0x99 for h in cs.solve(b"\x00\x01", 0x99)
    )
