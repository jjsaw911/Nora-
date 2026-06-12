"""Baud / framing discovery helper.

Line params for the NX-3320 are UNCONFIRMED. This module sweeps the hypothesis
space (``docs/prior-art.md`` §5) two ways:

* **Passive** (no TX, always safe): open the port at a candidate baud/framing,
  listen, and score how "UART-plausible" the received bytes look. Useful when the
  radio (or a KPG-D3 sniff) is already chattering.
* **Active** (requires ``allow_tx``): send the hypothesised enter-program-mode
  handshake at each candidate and watch for the expected ACK byte. Strictly
  allowlisted — only the handshake/read opcodes can ever be transmitted.

Active probing is **off unless the caller passes a link with ``allow_tx=True``**,
preserving the read-only-by-default guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import protocol
from .serialio import LineParams, SerialLink

# Candidate sweep, ordered by prior-art likelihood (H1 first).
CANDIDATE_BAUDS: tuple[int, ...] = (9600, 19200, 38400, 57600, 4800, 115200)
CANDIDATE_FRAMING: tuple[tuple[int, str, int], ...] = (
    (8, "N", 2),  # H1: 8N2
    (8, "N", 1),  # H1 post-handshake / H2
    (8, "E", 1),
    (8, "O", 1),
)


@dataclass(frozen=True)
class ProbeResult:
    params: LineParams
    score: float                 # higher = more plausible
    sample: bytes = b""
    handshake_ack: bool = False  # active probe only: saw expected ACK
    note: str = ""


def _plausibility(sample: bytes) -> float:
    """Heuristic UART-plausibility score for a passive sample.

    Rewards a healthy mix of printable + control bytes and presence of known
    protocol bytes (ACK/NAK/'W'/'Z'); penalises all-0x00 / all-0xFF / framing-error
    noise (which at the wrong baud tends to look like solid 0x00 or 0xFF runs).
    """
    if not sample:
        return 0.0
    n = len(sample)
    zeros = sample.count(0x00)
    ffs = sample.count(0xFF)
    if zeros == n or ffs == n:
        return 0.0
    distinct = len(set(sample))
    diversity = distinct / 256.0
    signal = sum(
        sample.count(b) for b in (protocol.ACK, protocol.NAK, protocol.RESP_DATA, protocol.RESP_EMPTY)
    )
    noise_penalty = (zeros + ffs) / (2 * n)
    return max(0.0, diversity + 0.1 * signal - 0.5 * noise_penalty)


def passive_scan(
    port: str,
    *,
    bauds: tuple[int, ...] = CANDIDATE_BAUDS,
    framings: tuple[tuple[int, str, int], ...] = CANDIDATE_FRAMING,
    listen_bytes: int = 64,
    timeout: float = 0.5,
) -> list[ProbeResult]:
    """Listen (no TX) at each candidate and score plausibility. Always safe."""
    results: list[ProbeResult] = []
    for baud in bauds:
        for bits, parity, stop in framings:
            params = LineParams(baudrate=baud, bytesize=bits, parity=parity, stopbits=stop, timeout=timeout)
            link = SerialLink(port=port, params=params, allow_tx=False)
            try:
                with link:
                    sample = link.drain(settle=timeout)
            except Exception as exc:  # noqa: BLE001 - report, keep sweeping
                results.append(ProbeResult(params, 0.0, note=f"open failed: {exc}"))
                continue
            results.append(ProbeResult(params, _plausibility(sample[:listen_bytes]), sample[:listen_bytes]))
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def active_handshake_probe(
    port: str,
    *,
    bauds: tuple[int, ...] = CANDIDATE_BAUDS,
    framings: tuple[tuple[int, str, int], ...] = CANDIDATE_FRAMING,
    expect_acks: tuple[int, ...] = (protocol.ACK, protocol.SPEED_ACK),
    timeout: float = 0.6,
) -> list[ProbeResult]:
    """Send the hypothesised enter-program handshake at each candidate.

    **Requires TX.** This function constructs links with ``allow_tx=True`` because
    its whole purpose is to transmit the (allowlisted) handshake; callers must opt
    in by invoking it (the CLI gates it behind ``--allow-tx``). Only
    ``protocol.build_enter_program()`` — an allowlisted opcode — is ever sent.
    """
    results: list[ProbeResult] = []
    frame = protocol.build_enter_program()  # raises if somehow not allowlisted
    for baud in bauds:
        for bits, parity, stop in framings:
            params = LineParams(baudrate=baud, bytesize=bits, parity=parity, stopbits=stop, timeout=timeout)
            link = SerialLink(port=port, params=params, allow_tx=True)
            try:
                with link:
                    reply = link.transact(frame, read_size=8)
            except Exception as exc:  # noqa: BLE001
                results.append(ProbeResult(params, 0.0, note=f"open failed: {exc}"))
                continue
            saw_ack = any(a in reply for a in expect_acks)
            score = (1.0 if saw_ack else 0.0) + _plausibility(reply)
            note = "handshake ACK!" if saw_ack else ("reply" if reply else "silence")
            results.append(ProbeResult(params, score, reply, handshake_ack=saw_ack, note=note))
    results.sort(key=lambda r: r.score, reverse=True)
    return results
