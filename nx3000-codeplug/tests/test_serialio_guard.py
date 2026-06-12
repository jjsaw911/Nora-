"""Tests for the read-only TX master gate in serialio.

These don't touch real hardware; they use a fake serial backing object to assert
that the off-by-default gate blocks transmission and that blocked opcodes never
reach the wire even when TX is enabled.
"""

import pytest

# Skip cleanly if pyserial isn't installed in the test env.
serial = pytest.importorskip("serial")

from nx3000 import protocol
from nx3000.serialio import LineParams, SerialLink, TxBlockedError


class _FakeSerial:
    """Minimal stand-in for serial.Serial that records writes."""

    def __init__(self):
        self.written = bytearray()
        self.is_open = True
        self.baudrate = 9600
        self.in_waiting = 0

    def write(self, data):
        self.written += data
        return len(data)

    def read(self, n=1):
        return b""

    def close(self):
        self.is_open = False


def _link(allow_tx):
    link = SerialLink(port="loop://", params=LineParams(), allow_tx=allow_tx)
    link._ser = _FakeSerial()  # inject fake, skip real open()
    return link


def test_tx_blocked_by_default():
    link = _link(allow_tx=False)
    with pytest.raises(TxBlockedError):
        link.write(b"PROGRAM")
    assert bytes(link._ser.written) == b""


def test_tx_allowed_when_gate_open_for_safe_opcode():
    link = _link(allow_tx=True)
    n = link.send(protocol.TxOpcode.READ_BLOCK, b"\x00\x01")
    assert n == 3
    assert bytes(link._ser.written) == b"R\x00\x01"


def test_blocked_opcode_refused_even_with_tx_enabled():
    link = _link(allow_tx=True)
    with pytest.raises(protocol.BlockedOpcodeError):
        link.send(protocol.TxOpcode.WRITE_BLOCK, b"\x00\x01")
    assert bytes(link._ser.written) == b""


def test_raw_write_validates_leading_opcode_when_tx_enabled():
    link = _link(allow_tx=True)
    with pytest.raises(protocol.BlockedOpcodeError):
        link.write(b"Z\x00\x01")  # 'Z' write-0xFF opcode must be refused
    assert bytes(link._ser.written) == b""


def test_set_baudrate_updates_both():
    link = _link(allow_tx=False)
    link.set_baudrate(19200)
    assert link.params.baudrate == 19200
    assert link._ser.baudrate == 19200
