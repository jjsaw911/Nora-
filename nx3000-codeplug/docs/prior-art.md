# Prior Art — Kenwood Serial Clone/Read Protocols (Phase 0)

Status: **research / hypotheses only.** Nothing here has been confirmed against an
NX-3320K3 yet. Everything is a *starting hypothesis* to iterate the spec against
once we have a capture. Confirmed facts migrate to `docs/protocol.md`.

Target unit: **Kenwood NX-3320K3** (NXDN/NEXEDGE UHF portable, NX-3000 series).
Official CPS: **KPG-D3** (`KPG-D3K`/`KPG-D3E`/`KPG-D3N` regional variants).

---

## 1. Why prior art is useful here

Kenwood has reused the same *clone-mode* serial framing conventions across many
generations of commercial radios (TK analog series, early NX series). The codeplug
contents differ wildly between models, but the **transport** — enter-program-mode
handshake, block read/write commands, ACK/NAK bytes, per-block checksum — tends to
rhyme. So rather than treat the NX-3000 as a fully black box, we seed our probing
with the best-documented Kenwood transport and look for deviations.

The single most useful open reference is the **CHIRP** project's family of Kenwood
clone-mode drivers, which are reverse-engineered and readable Python.

---

## 2. The CHIRP Kenwood TK clone-mode transport (best-documented analog)

CHIRP's `tk8180.py` driver (Kenwood TK-8180/TK-7180 and relatives) documents a
clone-mode protocol that is the closest well-understood analog to what the NX
series likely uses. Extracted protocol shape:

### Line params
- **Initial:** 9600 baud, 8 data bits, no parity, **2 stop bits**, ~1 s timeout.
- **After handshake the radio switches to 19200 baud** for the bulk transfer.
- (8N1 vs 8N2 is a thing to watch for — TK uses 8N2 initially.)

### Enter-program-mode handshake
1. Host sends ASCII `PROGRAM` at 9600 baud.
2. Radio replies `0x16` (acknowledges high-speed mode).
3. Host switches the port to 19200 baud.
4. Radio replies `0x06` (ACK, now in program mode).
5. Host sends `0x02` (request ident).
6. Radio returns an **8-byte ident** (e.g. `P3180\x06...`); host validates the
   model prefix and replies `0x06`.

### Block read (the part we care about for Phase 1)
- Command framing: `struct.pack(">BH", ord(cmd), addr)` — i.e. a one-byte command
  char followed by a **big-endian 16-bit address/block number**.
- Read command char: **`'R'`** (0x52), with `addr` = block number, range seen
  `0x0000`–`0xBF00`.
- Radio response:
  - **`'W'`** (0x57) → a full data block follows (256 bytes), or
  - **`'Z'`** (0x5A) → "this block is all 0xFF" (empty-block shorthand, no data).
- **Block size: 256 bytes.**
- **Checksum: 8-bit modular sum** over the block (`checksum_8bit`).
- Host ACKs each block with `0x06`.

### Extended memory region
- A second region (`0xC000`–`0xD1F0`) uses command **`'S'`** with a length byte
  `0x40`; the radio answers **`'X'`** followed by 0x40 (64) bytes.

### Write/erase commands (HARD-BLOCKED for us)
- Upload uses **`'W'`** (write block), **`'X'`** (write extended), **`'Z'`**
  (write all-0xFF block). Session end is **`'E'`**.
- ⚠️ These are exactly the opcodes our allowlist must **refuse to transmit**
  during Phase 1. Note the same letter `W`/`Z`/`X` appears as a *radio→host
  response* during reads but as a *host→radio command* during writes — direction
  matters, and our TX allowlist keys on host→radio opcodes.

### ACK/NAK bytes
- `0x06` = ACK, `0x16` = "speed OK", `0x15` = NAK (standard, watch for it).

---

## 3. Other Kenwood data points

- **Per-block checksum varies by model.** CHIRP notes some TK radios (e.g.
  TK-760G) add a checksum on each block while older ones do not, and there are
  open bugs about "Bad Checksum on block N" — confirming an 8-bit-sum-per-block
  scheme is common but model-specific. Treat the checksum algorithm as a
  *search* (see `checksum.py`), not a given.
- **Bank/zone structure.** Kenwood codeplugs are organized as multiple
  channel lists / zones rather than one flat channel array. Irrelevant to a raw
  block read, but relevant later if we ever decode fields (out of scope now).
- **The NX-3000 is NXDN-generation and newer than the TK analog line.** Expect
  possible differences: a larger codeplug, possibly a different initial baud, a
  longer or differently-structured ident, and possibly a CRC (CRC-16) rather than
  a plain 8-bit sum. These are the deviations we're hunting for.

---

## 4. The bi-pin / half-duplex reality

The NX-3320 portable uses a 2-pin programming jack with the cheap "Baofeng-style"
USB-serial cable. The data line is commonly **single-wire half-duplex**: host TX
and radio RX share one conductor, so a passive capture or even the host's own
read buffer will see the host's transmitted bytes echoed back interleaved with the
radio's reply. Implications:

- Our reader must tolerate/strip its own echoed TX bytes.
- A logic-analyzer trace of the data pin shows *both directions on one line* — the
  decoder must use timing/known-command boundaries to separate host vs radio.
- **This must be confirmed empirically** (pinout unconfirmed per owner). Some
  cables break out separate TX/RX; do not assume.

---

## 5. Hypotheses to probe (ranked)

These are the 2–3 most likely line-param + framing hypotheses to try first.
`autobaud.py` exists to walk these quickly.

### Hypothesis H1 — "TK clone transport, reused verbatim" (most likely)
- 9600 8N2 to start → `PROGRAM` → `0x16` → switch 19200 8N1 → `0x06`.
- `0x02` ident request, 8-byte ident with model prefix (maybe `NX3320`/`P33xx`).
- Block read `'R'` + big-endian 16-bit block no.; 256-byte blocks; response
  `'W'`(data) / `'Z'`(empty); 8-bit sum checksum; `0x06` ACK per block.
- **Rationale:** Kenwood's strongest reuse pattern; cheapest to confirm.

### Hypothesis H2 — "TK transport, but fixed high baud + CRC-16"
- Same handshake shape, but no 9600→19200 step (stays at one baud, possibly
  19200, 38400, or 57600), and per-block integrity is **CRC-16** not an 8-bit sum.
- **Rationale:** NXDN-generation firmware often modernizes integrity checking and
  the codeplug is large enough that a single higher baud is plausible.

### Hypothesis H3 — "NX-specific framing"
- A longer/different enter-prog handshake (NX radios sometimes need a model/
  password exchange), a 4-byte (`>I`) address for a large flat address space, and
  larger block sizes (512/1024). Checksum unknown → run the solver.
- **Rationale:** fallback if H1/H2 ident handshakes get NAK'd; the NX codeplug is
  much bigger than a TK's, which pressures address width and block size upward.

### Discovery order
1. Try H1 handshake passively-then-actively at 9600 8N2 (with `--allow-tx`).
2. If `PROGRAM` is NAK'd or silent, sweep baud/framing with `autobaud.py`.
3. Once any reply is seen, capture it and feed the bytes to `capture.py` +
   `checksum.py` solver to lock framing and the integrity algorithm.

---

## 6. Reference-capture (Path A) plan

Owner has the KPG-D3 CPS (to be reinstalled) and the cable. The fastest, no-extra-
hardware reference capture is a **software serial sniff**:

- **Windows:** insert a port sniffer between KPG-D3 and the real COM port — e.g. a
  `com0com` null-modem pair with a passthrough, or a passive COM-port monitor that
  logs both directions with timestamps. Run *one clean Read* in KPG-D3, save the
  log.
- Feed that timestamped log to `capture.py`, which separates directions and emits
  a framed byte stream. That decode hands us H1/H2/H3 confirmation almost
  outright.
- ⚠️ Sniffing only *observes* KPG-D3's own (legitimate, vendor) read transaction.
  Our tool still never originates a write.

---

## 7. Sources

- CHIRP — Kenwood driver family overview:
  <https://deepwiki.com/kk7ds/chirp/4.4-kenwood-driver-family>
- CHIRP — TK-8180 clone-mode driver source (transport details quoted above):
  <https://raw.githubusercontent.com/kk7ds/chirp/master/chirp/drivers/tk8180.py>
- CHIRP — `kenwood_live.py` (live-mode command set, for contrast):
  <https://chirp.danplanet.com/projects/chirp/repository/github/entry/chirp/drivers/kenwood_live.py>
- CHIRP issue #2835 — "Kenwood TK Commercial series" (handshake/ID/empty-block/
  checksum similarity across TK models):
  <https://chirpmyradio.com/issues/2835>
- CHIRP bug #12056 — "TK-762HG Bad Checksum on block 50" (per-block checksum is
  real and model-specific):
  <https://chirpmyradio.com/issues/12056>
- KPG-D3 product/scope confirmation (NX-3000/3200/3300/3400 series):
  <https://radiosoftware.online/KENWOOD/SOFTWARE/NX-3000-3200-3300-3400_(KPG-D3)/>
- RadioReference / myGMRS community threads on Kenwood programming (general):
  <https://forums.mygmrs.com/topic/3270-kenwood-programming/>
