# CLAUDE.md — NX-3000 Codeplug Reader (Phase 1: Read & Backup)

## Goal

Reverse-engineer the serial **read** protocol of the Kenwood NX-3000 series
(target unit: NX-3320K3, NXDN/NEXEDGE UHF portable) and build a tool that pulls
the radio's existing codeplug out as a raw binary blob — **without** the licensed
KPG-D3 CPS. This recovers the lost configuration and creates a permanent backup.

This is reverse engineering for interoperability with hardware the owner
possesses. Writing back to the radio and full field-level decoding are **future
phases** and are explicitly OUT OF SCOPE here.

## Non-negotiable safety rule

**READ-ONLY until the protocol is proven.** Do not transmit any byte sequence to
the radio that could be a write/erase/commit command. During discovery, only send
candidate *read* commands and the documented enter-program-mode handshake. A bad
write can brick the unit or corrupt the codeplug. Every serial-TX code path must
be gated behind an explicit, off-by-default `--allow-tx` flag, and write opcodes
must be hard-blocked by an allowlist of known-safe commands.

## What we're talking to

- **Interface:** Kenwood 2-pin ("bi-pin") programming jack. Treat the data line
  as **half-duplex single-wire UART** (TX and RX share the line; captures will
  show both directions interleaved). Confirm this empirically before assuming.
- **Adapter:** generic USB-serial (FTDI / CP210x / Prolific) presenting a COM/tty
  port — same cheap bi-pin cable used on Baofeng.
- **Line params are UNKNOWN.** Baud, framing, and idle level are discovery
  targets — do NOT hard-code them. Make them CLI-configurable and write a small
  autobaud/scan helper.

## Methodology (work these in order)

### Phase 0 — Seed hypotheses from prior art

Before touching hardware, research and summarize the known Kenwood clone/read
serial protocols (TK-series and earlier NX-series community docs, sigrok/CHIRP
notes, RadioReference threads). Kenwood reuses framing conventions across
generations; start from those as hypotheses rather than fully black-box. Capture
findings in `docs/prior-art.md` with citations.

### Phase 1 — Capture & decode framing

Two capture sources, support both:

- **(A) Reference capture (fast path):** if a working KPG-D3 instance is ever
  available (even briefly, on someone else's machine), capture one clean *read*
  transaction. Decode it; this hands us the protocol almost outright.
- **(B) Black-box probing (likely path):** interactively send candidate enter-
  prog-mode + block-read commands and log responses. Read-only, allowlisted.

For capture, prefer a **logic-analyzer trace of the data pin** decoded as async
UART (sigrok/PulseView, or `sigrok-cli` import). Build a parser that ingests a
decoded byte stream (CSV/VCD) and a raw `.bin` and extracts framing.

Deliverable: `docs/protocol.md` — a living spec that fills in as fields are
confirmed: line params, enter-prog handshake, block-read command structure,
address/length encoding, response framing, checksum/CRC algorithm, ACK/NAK.

### Phase 2 — Implement the reader

A `pyserial` reader that: opens the port, performs the handshake, walks the
address space issuing block reads, validates each block's checksum, reassembles
the full codeplug, and writes `codeplug_<serial>_<timestamp>.bin` plus a sidecar
JSON manifest (radio model/serial/firmware if obtainable via a transceiver-info
query, capture params, per-block checksum log).

### Phase 3 — Verify

Read the radio **twice** and assert byte-identical blobs. Cross-check total size
against the expected NX-3000 codeplug size. Confirm recomputed checksums match.
Only a verified, repeatable read counts as success.

## Tech stack

- Python 3.11+, `pyserial`. Keep deps minimal.
- Optional: `sigrok-cli` for logic-capture import; `crccheck` for CRC search.
- Clean CLI (`argparse` or `click`): subcommands `scan`, `probe`, `capture-parse`,
  `read`, `verify`. No GUI.
- Cross-platform serial (Windows COM + Linux tty).

## Repo structure to scaffold

```
nx3000-codeplug/
  CLAUDE.md                 # this file
  README.md
  pyproject.toml
  docs/
    prior-art.md            # Phase 0 output
    protocol.md             # living spec, filled incrementally
    capture-log.md          # what was tried, what the radio answered
  src/nx3000/
    serialio.py             # port open, half-duplex handling, framing read
    autobaud.py             # baud/framing discovery helper
    protocol.py             # command builders + response parsers (spec-driven)
    checksum.py             # candidate checksum/CRC implementations + solver
    reader.py               # Phase 2 block-walk reader
    capture.py              # parse logic-analyzer / sniffer captures
    cli.py
  tests/                    # parser/checksum unit tests on captured fixtures
  captures/                 # raw + decoded capture fixtures (gitignored if large)
```

## First tasks for you (Claude Code), in order

1. Scaffold the repo above; stub modules with docstrings; set up `pyproject.toml`
   and a `read-only by default` TX guard in `serialio.py`.
1. Do Phase 0 research and write `docs/prior-art.md`. Propose the 2–3 most likely
   line-param + framing hypotheses for an NX-3000 with reasoning.
1. Build `capture.py` + `autobaud.py` so I can feed in a logic capture and get a
   decoded, framed byte stream out — this is what we'll iterate the spec against.
1. Stub `protocol.py` and `reader.py` against the *hypothesized* spec so they're
   ready the moment a capture confirms framing. Do NOT enable any TX path yet.
1. Write `docs/protocol.md` as a template with every unknown explicitly marked
   `TODO/UNCONFIRMED` so we track exactly what's been proven vs assumed.

## Things to ASK me, don't assume

- Whether I have any access to a working KPG-D3 CPS for a reference capture
  (Path A) or we go fully black-box (Path B).
- My capture hardware (logic analyzer model / second serial adapter) so capture
  parsing targets the right export format.
- Confirmation of the bi-pin pinout / which pin is data on my specific cable.

## Definition of done (Phase 1)

A documented read protocol in `docs/protocol.md` and a `read` command that pulls a
checksum-valid, byte-reproducible codeplug blob off the NX-3320K3 and saves it
with a manifest — with zero write commands ever sent to the radio.

---

## Session decisions (recorded answers to the "ASK me" items)

> Captured 2026-06-12 from the project owner. Update if these change.

- **Path A vs B:** Owner **has the KPG-D3 software** (needs reinstalling), so a
  reference capture is realistically available. Plan for **both**: Path B
  (black-box, allowlisted probing) is the near-term route, but the Path A
  reference-decode pipeline must be ready. With CPS + cable in hand, the cheapest
  reference capture is a **software serial sniff** of KPG-D3 ↔ radio traffic — no
  logic analyzer required.
- **Capture hardware:** Owner has the **programming cable** (bi-pin USB-serial),
  no dedicated logic analyzer yet. `capture.py` therefore ingests **generic
  decoded-byte CSV, raw `.bin`, and timestamped serial-sniff logs**, and can
  later accept sigrok CSV/VCD if a logic analyzer is added.
- **Bi-pin pinout / data line / idle level:** **UNCONFIRMED** — treated as a
  discovery target throughout the docs and code.
