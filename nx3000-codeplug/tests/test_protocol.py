"""Tests for the protocol command builders, the TX allowlist, and the parser.

These lock in the **safety-critical** behaviour: write/erase opcodes must never
build into a transmittable frame.
"""

import struct

import pytest

from nx3000 import protocol as p


# --- Allowlist / safety ----------------------------------------------------


@pytest.mark.parametrize("opcode", [
    p.TxOpcode.PROGRAM, p.TxOpcode.IDENT, p.TxOpcode.ACK,
    p.TxOpcode.END, p.TxOpcode.READ_BLOCK, p.TxOpcode.READ_EXT,
])
def test_safe_opcodes_build(opcode):
    # Should not raise.
    p.build_command(opcode)


@pytest.mark.parametrize("opcode", [
    p.TxOpcode.WRITE_BLOCK, p.TxOpcode.WRITE_EXT, p.TxOpcode.WRITE_FF,
])
def test_write_opcodes_are_blocked(opcode):
    with pytest.raises(p.BlockedOpcodeError):
        p.build_command(opcode)


def test_unknown_opcode_blocked():
    with pytest.raises(p.BlockedOpcodeError):
        p.build_command(b"\x99")


def test_assert_safe_opcode_message_mentions_readonly():
    with pytest.raises(p.BlockedOpcodeError, match="read-only"):
        p.assert_safe_opcode(p.TxOpcode.WRITE_BLOCK)


def test_write_and_safe_sets_disjoint():
    assert p.SAFE_TX_OPCODES.isdisjoint(p.BLOCKED_TX_OPCODES)


# --- Command framing -------------------------------------------------------


def test_build_read_block_framing():
    frame = p.build_read_block(0x00BF)
    assert frame == b"R" + struct.pack(">H", 0x00BF)


def test_build_read_block_range_check():
    with pytest.raises(ValueError):
        p.build_read_block(0x1_0000)


def test_build_read_ext_appends_length():
    frame = p.build_read_ext(0xC000, 0x40)
    assert frame[:1] == b"S"
    assert frame[-1] == 0x40


# --- Response parsing ------------------------------------------------------


def test_parse_empty_block():
    resp = p.parse_block_response(bytes([p.RESP_EMPTY]))
    assert resp.kind is p.BlockKind.EMPTY
    assert resp.data == b"\xff" * p.BLOCK_SIZE


def test_parse_data_block_with_checksum():
    payload = bytes(range(256))
    buf = bytes([p.RESP_DATA]) + payload + b"\x2a"
    resp = p.parse_block_response(buf)
    assert resp.kind is p.BlockKind.DATA
    assert resp.data == payload
    assert resp.checksum == 0x2A


def test_parse_short_block_raises():
    with pytest.raises(p.ProtocolError):
        p.parse_block_response(bytes([p.RESP_DATA]) + b"\x00" * 10)


def test_parse_unexpected_tag_raises():
    with pytest.raises(p.ProtocolError):
        p.parse_block_response(b"\x99rest")
