"""Serial port I/O with a read-only-by-default TX guard and half-duplex handling.

This module is the **only** place that touches the wire. It implements the first
half of the read-only safety guarantee:

* ``allow_tx`` defaults to ``False``. With it off, **no byte ever leaves the
  port** — :meth:`SerialLink.write` raises. ``scan`` / ``capture-parse`` run in
  this mode.
* When ``allow_tx`` is on, every outgoing frame is still routed through the
  protocol allowlist (:func:`nx3000.protocol.assert_safe_opcode`), so write/erase
  opcodes are hard-blocked even when TX is enabled.

It also handles the **half-duplex single-wire** reality (UNCONFIRMED for the
NX-3320): on a shared TX/RX conductor the host hears its own transmitted bytes
echoed back. :meth:`SerialLink.transact` can strip that echo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

try:  # pyserial is the one hard runtime dep; keep import failure legible.
    import serial  # type: ignore
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise ImportError(
        "pyserial is required for serial I/O. Install with `pip install pyserial` "
        "(or `pip install -e .`)."
    ) from exc

from . import protocol


class TxBlockedError(RuntimeError):
    """Raised when a TX is attempted while the read-only master gate is engaged."""


@dataclass
class LineParams:
    """UART line parameters. All UNCONFIRMED for the NX-3320 (discovery targets)."""

    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"          # 'N', 'E', 'O', 'M', 'S'
    stopbits: float = 2        # H1 hypothesis: 8N2 initially
    timeout: float = 1.0       # read timeout (s)
    write_timeout: float = 1.0

    def as_pyserial_kwargs(self) -> dict:
        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
            "M": serial.PARITY_MARK,
            "S": serial.PARITY_SPACE,
        }
        stop_map = {
            1: serial.STOPBITS_ONE,
            1.5: serial.STOPBITS_ONE_POINT_FIVE,
            2: serial.STOPBITS_TWO,
        }
        bytesize_map = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }
        return {
            "baudrate": self.baudrate,
            "bytesize": bytesize_map[self.bytesize],
            "parity": parity_map[self.parity.upper()],
            "stopbits": stop_map[self.stopbits],
            "timeout": self.timeout,
            "write_timeout": self.write_timeout,
        }

    def __str__(self) -> str:
        sb = int(self.stopbits) if float(self.stopbits).is_integer() else self.stopbits
        return f"{self.baudrate} {self.bytesize}{self.parity}{sb}"


@dataclass
class SerialLink:
    """A guarded serial connection to the radio.

    Open with :meth:`open` or use as a context manager. TX is disabled unless
    ``allow_tx=True`` (the off-by-default master gate), and even then only
    allowlisted opcodes may be sent.
    """

    port: str
    params: LineParams = field(default_factory=LineParams)
    allow_tx: bool = False
    half_duplex: bool = True        # assume shared TX/RX line (UNCONFIRMED)
    _ser: "serial.Serial | None" = field(default=None, init=False, repr=False)
    tx_log: list[bytes] = field(default_factory=list, init=False, repr=False)
    rx_log: list[bytes] = field(default_factory=list, init=False, repr=False)

    # -- lifecycle ----------------------------------------------------------

    def open(self) -> "SerialLink":
        self._ser = serial.Serial(port=self.port, **self.params.as_pyserial_kwargs())
        return self

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self) -> "SerialLink":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _require_open(self) -> "serial.Serial":
        if self._ser is None or not self._ser.is_open:
            raise RuntimeError("serial port is not open; call .open() first")
        return self._ser

    # -- line param changes (e.g. 9600 -> 19200 after handshake) ------------

    def set_baudrate(self, baudrate: int) -> None:
        ser = self._require_open()
        ser.baudrate = baudrate
        self.params.baudrate = baudrate

    # -- RX (always allowed) ------------------------------------------------

    def read(self, size: int = 1) -> bytes:
        data = self._require_open().read(size)
        if data:
            self.rx_log.append(data)
        return data

    def read_until(self, expected: bytes = b"", max_bytes: int = 4096) -> bytes:
        """Read until ``expected`` is seen, ``max_bytes`` read, or timeout."""
        ser = self._require_open()
        out = bytearray()
        while len(out) < max_bytes:
            b = ser.read(1)
            if not b:
                break  # timeout
            out += b
            if expected and out.endswith(expected):
                break
        if out:
            self.rx_log.append(bytes(out))
        return bytes(out)

    def drain(self, settle: float = 0.05) -> bytes:
        """Read whatever is currently buffered (passive listen). No TX."""
        ser = self._require_open()
        time.sleep(settle)
        n = ser.in_waiting
        data = ser.read(n) if n else b""
        if data:
            self.rx_log.append(data)
        return data

    # -- TX (gated) ---------------------------------------------------------

    def write(self, frame: bytes, *, _opcode_checked: bool = False) -> int:
        """Transmit ``frame`` — only if the master gate is open AND it is safe.

        Two independent guards must both pass:

        1. ``allow_tx`` must be True (off-by-default master gate).
        2. The frame's opcode must be allowlisted (unless ``_opcode_checked``,
           used by :meth:`send` which already validated via the protocol layer).

        Raises :class:`TxBlockedError` / ``protocol.BlockedOpcodeError`` otherwise.
        """
        if not self.allow_tx:
            raise TxBlockedError(
                "TX is disabled (read-only mode). Re-run with --allow-tx to permit "
                "transmitting the handshake / read commands. This is the safety gate."
            )
        if not _opcode_checked and frame:
            # Validate against the allowlist. Multi-byte commands (PROGRAM) and
            # single-byte ones are both covered by exact-membership in build_command;
            # here we re-check the leading opcode token defensively.
            protocol.assert_safe_opcode(frame if frame in protocol.SAFE_TX_OPCODES else frame[:1])
        n = self._require_open().write(frame)
        self.tx_log.append(frame)
        return n

    def send(self, opcode: "bytes | protocol.TxOpcode", payload: bytes = b"") -> int:
        """Build (allowlist-checked) and transmit a protocol frame."""
        frame = protocol.build_command(opcode, payload)  # raises on blocked opcode
        return self.write(frame, _opcode_checked=True)

    def transact(self, frame: bytes, *, read_size: int = 256, strip_echo: bool = True) -> bytes:
        """Send ``frame`` and read the reply, optionally stripping half-duplex echo.

        On a single-wire line the leading bytes of the reply are the host's own
        ``frame`` echoed back; when ``strip_echo`` and ``half_duplex`` are set we
        discard a matching prefix.
        """
        self.write(frame, _opcode_checked=False)
        reply = self.read(read_size)
        if strip_echo and self.half_duplex and reply.startswith(frame):
            reply = reply[len(frame):]
        return reply
