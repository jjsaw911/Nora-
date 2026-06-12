"""Command builders and response parsers for the NX-3000 read protocol.

**Spec-driven and UNCONFIRMED.** Every constant here is a *hypothesis* seeded
from the CHIRP TK-x180 clone-mode transport (see ``docs/prior-art.md``) and must
be confirmed against a real NX-3320K3 capture before it is trusted. The matching
spec doc is ``docs/protocol.md``; keep the two in sync.

This module deliberately contains **no I/O**. It only builds byte frames and
parses byte buffers, so it is trivially unit-testable on captured fixtures. The
single hard rule it enforces is the **TX allowlist**: it refuses to build any
host→radio frame whose opcode is not known-safe (read/handshake only). Write and
erase opcodes raise :class:`BlockedOpcodeError`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Opcodes (host -> radio).  Values are ASCII command chars or control bytes.
# Status of every one of these is UNCONFIRMED (hypothesis H1 from prior art).
# ---------------------------------------------------------------------------


class TxOpcode(bytes, Enum):
    """Host→radio command opcodes we know (or hypothesize) the radio accepts."""

    # --- Handshake / control (safe) ---
    PROGRAM = b"PROGRAM"      # enter program mode
    IDENT = b"\x02"           # request transceiver ident
    ACK = b"\x06"             # acknowledge
    END = b"E"                # end session (host->radio; benign)

    # --- Reads (safe) ---
    READ_BLOCK = b"R"         # read a 256-byte block (addr = block number)
    READ_EXT = b"S"           # read an extended/short block

    # --- Writes / erase (NEVER send during Phase 1) ---
    WRITE_BLOCK = b"W"        # write a block
    WRITE_EXT = b"X"          # write an extended block
    WRITE_FF = b"Z"           # write an all-0xFF block


# Opcodes the tool is permitted to transmit. Anything not in here is hard-blocked
# by build_command(), independently of the --allow-tx master gate in serialio.
# Keep this in lockstep with the table in docs/protocol.md §8.
SAFE_TX_OPCODES: frozenset[bytes] = frozenset(
    {
        TxOpcode.PROGRAM.value,
        TxOpcode.IDENT.value,
        TxOpcode.ACK.value,
        TxOpcode.END.value,
        TxOpcode.READ_BLOCK.value,
        TxOpcode.READ_EXT.value,
    }
)

# Explicitly enumerated for clarity / error messages. (Anything not in SAFE is
# blocked regardless; this set is the "we specifically know this is dangerous".)
BLOCKED_TX_OPCODES: frozenset[bytes] = frozenset(
    {
        TxOpcode.WRITE_BLOCK.value,
        TxOpcode.WRITE_EXT.value,
        TxOpcode.WRITE_FF.value,
    }
)

# Response bytes (radio -> host).  UNCONFIRMED.
ACK = 0x06
NAK = 0x15
SPEED_ACK = 0x16
RESP_DATA = ord("W")   # radio: a data block follows
RESP_EMPTY = ord("Z")  # radio: this block is all 0xFF (no data)
RESP_EXT = ord("X")    # radio: extended block follows

# Hypothesised framing constants (H1).  UNCONFIRMED.
BLOCK_SIZE = 256
EXT_BLOCK_SIZE = 0x40
ADDR_STRUCT = ">H"     # big-endian 16-bit block number / address


class BlockedOpcodeError(RuntimeError):
    """Raised when code attempts to build a frame with a non-allowlisted opcode.

    This is the protocol-level half of the read-only safety guarantee (the other
    half is the off-by-default ``--allow-tx`` gate in :mod:`nx3000.serialio`).
    """


def _opcode_byte(opcode: bytes | TxOpcode) -> bytes:
    return opcode.value if isinstance(opcode, TxOpcode) else bytes(opcode)


def assert_safe_opcode(opcode: bytes | TxOpcode) -> None:
    """Raise :class:`BlockedOpcodeError` unless ``opcode`` is allowlisted.

    The check keys on the *first* byte of multi-byte commands (e.g. ``PROGRAM``)
    by exact membership, so ``b"PROGRAM"`` is matched whole and a stray ``b"W"``
    is rejected.
    """
    raw = _opcode_byte(opcode)
    if raw not in SAFE_TX_OPCODES:
        why = "known write/erase opcode" if raw in BLOCKED_TX_OPCODES else "unknown opcode"
        raise BlockedOpcodeError(
            f"Refusing to build TX frame for {raw!r} ({why}). "
            f"Phase 1 is read-only; only {sorted(SAFE_TX_OPCODES)} may be sent."
        )


# ---------------------------------------------------------------------------
# Command builders (host -> radio).  Each routes through assert_safe_opcode().
# ---------------------------------------------------------------------------


def build_command(opcode: bytes | TxOpcode, payload: bytes = b"") -> bytes:
    """Build a raw host→radio frame, enforcing the TX allowlist.

    Returns the bytes to transmit. Raises :class:`BlockedOpcodeError` for any
    non-allowlisted opcode. This is the single chokepoint every TX builder uses.
    """
    assert_safe_opcode(opcode)
    return _opcode_byte(opcode) + payload


def build_enter_program() -> bytes:
    """Frame for the enter-program-mode handshake (step 1). UNCONFIRMED."""
    return build_command(TxOpcode.PROGRAM)


def build_ident_request() -> bytes:
    """Frame requesting the transceiver ident. UNCONFIRMED."""
    return build_command(TxOpcode.IDENT)


def build_read_block(block_no: int) -> bytes:
    """Frame to read one ``BLOCK_SIZE`` block by number. UNCONFIRMED (H1).

    Hypothesis: ``'R'`` + big-endian 16-bit block number.
    """
    if not 0 <= block_no <= 0xFFFF:
        raise ValueError(f"block_no out of 16-bit range: {block_no}")
    return build_command(TxOpcode.READ_BLOCK, struct.pack(ADDR_STRUCT, block_no))


def build_read_ext(addr: int, length: int = EXT_BLOCK_SIZE) -> bytes:
    """Frame to read an extended/short block. UNCONFIRMED (H1)."""
    if not 0 <= addr <= 0xFFFF:
        raise ValueError(f"addr out of 16-bit range: {addr}")
    return build_command(TxOpcode.READ_EXT, struct.pack(ADDR_STRUCT, addr) + bytes([length & 0xFF]))


def build_ack() -> bytes:
    """The single-byte ACK frame."""
    return build_command(TxOpcode.ACK)


def build_end_session() -> bytes:
    """End-of-session frame. UNCONFIRMED."""
    return build_command(TxOpcode.END)


# ---------------------------------------------------------------------------
# Response parsing (radio -> host).  Pure, fixture-testable.
# ---------------------------------------------------------------------------


class BlockKind(Enum):
    DATA = "data"        # a real data block
    EMPTY = "empty"      # radio said "all 0xFF" (RESP_EMPTY)
    EXT = "ext"          # extended block


@dataclass(frozen=True)
class BlockResponse:
    """A parsed radio block response.

    ``data`` is the payload (synthesised as 0xFF*BLOCK_SIZE for EMPTY blocks).
    ``checksum`` is the trailing integrity byte if one was present (None until we
    confirm whether reads carry a checksum — see docs/protocol.md §4).
    """

    kind: BlockKind
    data: bytes
    checksum: int | None = None
    raw: bytes = b""


class ProtocolError(RuntimeError):
    """Radio response did not match the (hypothesised) framing."""


def parse_block_response(buf: bytes, block_size: int = BLOCK_SIZE) -> BlockResponse:
    """Parse a single block response from ``buf``. UNCONFIRMED framing (H1).

    This is intentionally permissive about the trailing checksum because we have
    not yet confirmed whether read responses carry one. It recognises:

    * ``RESP_EMPTY`` (``'Z'``)            -> EMPTY block, no payload.
    * ``RESP_DATA`` (``'W'``) + N bytes   -> DATA block (+ optional checksum byte).

    Update this parser once a capture confirms the real framing.
    """
    if not buf:
        raise ProtocolError("empty response buffer")

    tag = buf[0]
    if tag == RESP_EMPTY:
        return BlockResponse(BlockKind.EMPTY, b"\xff" * block_size, raw=buf[:1])

    if tag == RESP_DATA:
        body = buf[1:]
        if len(body) < block_size:
            raise ProtocolError(
                f"short DATA block: got {len(body)} payload bytes, expected >= {block_size}"
            )
        data = body[:block_size]
        # If there is exactly one trailing byte, treat it (tentatively) as a checksum.
        trailing = body[block_size:]
        checksum = trailing[0] if len(trailing) >= 1 else None
        return BlockResponse(BlockKind.DATA, data, checksum=checksum, raw=buf)

    raise ProtocolError(f"unexpected block tag 0x{tag:02x} (expected 'W'/0x57 or 'Z'/0x5A)")
