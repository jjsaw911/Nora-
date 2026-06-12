# NX-3000 Codeplug Reader

A **read-only** tool to back up the codeplug of a **Kenwood NX-3320K3**
(NXDN/NEXEDGE UHF portable, NX-3000 series) over its serial programming jack —
**without** the licensed KPG-D3 CPS. This recovers a lost configuration and
creates a permanent binary backup for hardware you own.

> **Phase 1 = read & backup only.** Writing back to the radio and decoding
> individual codeplug fields are explicitly **out of scope**. See `CLAUDE.md`.

## ⚠️ Safety: read-only by default

A bad write can brick the radio or corrupt the codeplug, so this tool is built
read-only-first with **two independent guards**:

1. **Master TX gate** — no byte is transmitted unless you pass `--allow-tx`
   (off by default). `scan` and `capture-parse` never transmit.
2. **Opcode allowlist** — even with `--allow-tx`, only known-safe
   read/handshake opcodes (`PROGRAM`, ident, ACK, `R`, `S`, `E`) can reach the
   wire. Write/erase opcodes (`W`, `X`, `Z`) and anything unknown are
   hard-blocked in `protocol.py` and raise an error.

See `docs/protocol.md` §8 for the allowlist table.

## Status

The NX-3000 serial read protocol is **not yet confirmed**. Everything in
`protocol.py` / `reader.py` is wired against a *hypothesis* (Hypothesis H1) seeded
from the CHIRP TK-x180 clone-mode transport — see `docs/prior-art.md`. The spec in
`docs/protocol.md` marks every field `CONFIRMED` / `UNCONFIRMED` / `TODO` so we
always know what's proven vs assumed. **Do not trust a read until it's verified.**

## Install

```sh
cd nx3000-codeplug
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"        # add ",crc" for the extended CRC catalogue
```

Python 3.11+. Only hard dependency is `pyserial`.

## Usage

```sh
# 1. Passive listen — never transmits. Sanity-check the line / hunt for a baud.
nx3000 scan --port /dev/ttyUSB0

# 2. Decode a capture (KPG-D3 sniff, logic-analyzer CSV, or raw .bin) into a
#    framed byte stream, and optionally identify the checksum algorithm.
nx3000 capture-parse captures/kpgd3_read.csv
nx3000 capture-parse captures/block0.bin --solve-checksum --block captures/block0.bin --expected 0x2a

# 3. Active handshake sweep — REQUIRES --allow-tx (sends only allowlisted PROGRAM).
nx3000 probe --port /dev/ttyUSB0 --allow-tx

# 4. Read the codeplug (Phase 2) — REQUIRES --allow-tx. Writes a .bin + manifest.
nx3000 read --port /dev/ttyUSB0 --allow-tx --serial ABC1234 --out backups/

# 5. Verify (Phase 3) — read twice, assert byte-identical.
nx3000 verify --port /dev/ttyUSB0 --allow-tx
```

On Windows use `--port COM3` (etc.).

## Workflow (how we get from "unknown" to "verified backup")

1. **Seed** hypotheses from prior art → `docs/prior-art.md` (done).
2. **Capture** one clean read — ideally a KPG-D3 software sniff (Path A), else
   black-box `probe` (Path B) — and decode it with `capture-parse`.
3. **Confirm** framing + checksum; promote fields in `docs/protocol.md` from
   `UNCONFIRMED` to `CONFIRMED`, adding a test fixture for each.
4. **Read** with the confirmed spec; **verify** two byte-identical reads.

Log every attempt in `docs/capture-log.md`.

## Project layout

```
nx3000-codeplug/
  CLAUDE.md            # project brief + recorded session decisions
  docs/
    prior-art.md       # Phase 0 research (Kenwood TK/NX transport)
    protocol.md        # living spec — CONFIRMED/UNCONFIRMED/TODO per field
    capture-log.md     # journal of attempts + radio responses
  src/nx3000/
    serialio.py        # guarded serial I/O (TX master gate + half-duplex)
    autobaud.py        # passive/active baud + framing discovery
    protocol.py        # command builders + parsers + TX allowlist
    checksum.py        # candidate checksums/CRCs + solver
    reader.py          # Phase 2 block-walk reader + manifest writer
    capture.py         # logic-analyzer / sniffer capture parsing
    cli.py             # argparse CLI
  tests/               # unit tests (protocol/checksum/capture/TX-guard)
  captures/            # raw + decoded fixtures (large ones gitignored)
```

## Tests

```sh
pytest
```

Covers the checksum candidates/solver, the protocol framing + **TX allowlist**,
the capture parsers, and the read-only master gate.
