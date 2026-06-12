"""Phase 2 block-walk reader (stubbed against the *hypothesised* spec).

This walks the radio's address space issuing block reads, validates each block's
checksum, reassembles the full codeplug, and writes the ``.bin`` plus a JSON
manifest. It is wired against the UNCONFIRMED hypothesis-H1 framing so it is ready
the moment a capture confirms the spec — but it **does not transmit anything**
unless given a :class:`SerialLink` with ``allow_tx=True`` (and even then only
allowlisted read/handshake opcodes can leave the wire).

⚠️ Until the protocol is confirmed, treat a successful-looking run with extreme
suspicion: verify with the ``verify`` flow (read twice, compare) before trusting
any blob.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import checksum as _checksum
from . import protocol
from .serialio import SerialLink


@dataclass
class BlockRecord:
    """Per-block log entry for the manifest."""

    index: int
    addr: int
    kind: str
    length: int
    checksum_rx: int | None
    checksum_ok: bool | None  # None = couldn't validate (algorithm unconfirmed)


@dataclass
class ReadConfig:
    """Knobs for the block walk. Defaults are UNCONFIRMED (hypothesis H1)."""

    start_block: int = 0x00
    end_block: int = 0xBF          # inclusive; H1 main region 0x00..0xBF
    block_size: int = protocol.BLOCK_SIZE
    checksum_algorithm: str | None = None  # e.g. "sum8" once confirmed; None=skip-verify
    inter_block_delay: float = 0.0
    handshake: bool = True


@dataclass
class ReadResult:
    data: bytes
    blocks: list[BlockRecord] = field(default_factory=list)
    ident: bytes = b""
    params: dict = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


class ReaderError(RuntimeError):
    pass


def _validate_checksum(data: bytes, rx: int | None, algorithm: str | None) -> bool | None:
    if rx is None or algorithm is None:
        return None
    fn = _checksum.CANDIDATES.get(algorithm)
    if fn is None:
        raise ReaderError(f"unknown checksum algorithm {algorithm!r}")
    return fn(data) == rx


def enter_program_mode(link: SerialLink) -> bytes:
    """Perform the hypothesised handshake and return the ident bytes.

    UNCONFIRMED (H1). Sends only allowlisted opcodes. Returns the raw ident so the
    caller can record model/serial in the manifest.
    """
    # Step 1: PROGRAM -> expect speed/ack
    reply = link.transact(protocol.build_enter_program(), read_size=8)
    if protocol.SPEED_ACK in reply or protocol.ACK in reply:
        # Step 2 (H1): bump to bulk baud. UNCONFIRMED which baud; leave to caller
        # via params — here we just continue at the current baud if unspecified.
        pass
    # Step 3: request ident
    ident = link.transact(protocol.build_ident_request(), read_size=8)
    return ident


def read_codeplug(link: SerialLink, config: ReadConfig | None = None) -> ReadResult:
    """Walk blocks ``start..end`` and reassemble the codeplug.

    Requires ``link.allow_tx`` (it must transmit read commands). Raises if TX is
    gated off, surfacing the safety mechanism rather than silently doing nothing.
    """
    config = config or ReadConfig()
    if not link.allow_tx:
        raise ReaderError(
            "read_codeplug needs to transmit read commands, but the link is in "
            "read-only mode. Re-run with --allow-tx (only allowlisted read/handshake "
            "opcodes can ever be sent)."
        )

    ident = enter_program_mode(link) if config.handshake else b""

    out = bytearray()
    records: list[BlockRecord] = []
    for i, blk in enumerate(range(config.start_block, config.end_block + 1)):
        frame = protocol.build_read_block(blk)
        # Reply = tag + up to block_size (+ optional checksum). Read generously.
        reply = link.transact(frame, read_size=config.block_size + 4)
        resp = protocol.parse_block_response(reply, block_size=config.block_size)
        ok = _validate_checksum(resp.data, resp.checksum, config.checksum_algorithm)
        out += resp.data
        records.append(
            BlockRecord(
                index=i,
                addr=blk,
                kind=resp.kind.value,
                length=len(resp.data),
                checksum_rx=resp.checksum,
                checksum_ok=ok,
            )
        )
        # ACK each block (allowlisted) before requesting the next.
        link.send(protocol.TxOpcode.ACK)
        if config.inter_block_delay:
            time.sleep(config.inter_block_delay)

    return ReadResult(
        data=bytes(out),
        blocks=records,
        ident=ident,
        params={
            "line": str(link.params),
            "start_block": config.start_block,
            "end_block": config.end_block,
            "block_size": config.block_size,
            "checksum_algorithm": config.checksum_algorithm,
        },
    )


def save(result: ReadResult, out_dir: str | Path = ".", serial: str | None = None) -> tuple[Path, Path]:
    """Write ``codeplug_<serial>_<timestamp>.bin`` plus a sidecar JSON manifest.

    Returns ``(bin_path, manifest_path)``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    serial = serial or "unknown"
    bin_path = out_dir / f"codeplug_{serial}_{ts}.bin"
    manifest_path = out_dir / f"codeplug_{serial}_{ts}.json"

    bin_path.write_bytes(result.data)

    manifest = {
        "model": "NX-3320K3",
        "serial": serial,
        "ident_hex": result.ident.hex(),
        "captured_at": ts,
        "size_bytes": len(result.data),
        "sha256": result.sha256,
        "params": result.params,
        "blocks": [asdict(b) for b in result.blocks],
        "spec_status": "UNCONFIRMED — see docs/protocol.md before trusting this blob",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return bin_path, manifest_path


def verify_two_reads(a: ReadResult, b: ReadResult) -> bool:
    """Phase 3: two reads must be byte-identical to count as success."""
    return a.data == b.data and len(a.data) > 0
