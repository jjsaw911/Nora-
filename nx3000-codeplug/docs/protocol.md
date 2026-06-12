# NX-3000 Serial Read Protocol — Living Spec

> **Legend:** `CONFIRMED` = proven against an NX-3320K3 capture.
> `UNCONFIRMED` = hypothesis from prior art (see `docs/prior-art.md`), not yet
> verified. `TODO` = not yet investigated. **Do not promote anything to
> CONFIRMED without a capture/test fixture backing it.**

Target: **Kenwood NX-3320K3**. Source of hypotheses: CHIRP TK-x180 transport.

---

## 0. Status summary

| Area                     | Status        |
| ------------------------ | ------------- |
| Line params (baud/frame) | `UNCONFIRMED` |
| Half-duplex single-wire  | `UNCONFIRMED` |
| Enter-prog handshake     | `UNCONFIRMED` |
| Ident / model query      | `UNCONFIRMED` |
| Block-read command       | `UNCONFIRMED` |
| Address/length encoding  | `UNCONFIRMED` |
| Response framing         | `UNCONFIRMED` |
| Checksum / CRC algorithm | `UNCONFIRMED` |
| ACK / NAK bytes          | `UNCONFIRMED` |
| Total codeplug size      | `TODO`        |

---

## 1. Physical / line parameters

- **Interface:** Kenwood 2-pin programming jack, cheap USB-serial cable.
- **Data line / pinout:** `UNCONFIRMED` — which pin carries data and the idle
  level are discovery targets. Confirm with `nx3000 scan` / a multimeter before
  trusting any read.
- **Half-duplex single-wire:** `UNCONFIRMED` — assume TX/RX share one conductor
  (host echo will appear in RX). Confirm empirically.
- **Baud:** `UNCONFIRMED`. Hypotheses (in order): `9600` initial → `19200` bulk
  (H1); fixed `19200`/`38400`/`57600` (H2/H3).
- **Framing:** `UNCONFIRMED`. Hypothesis: `8N2` initial, possibly `8N1` after
  handshake (H1).
- **Idle level:** `UNCONFIRMED`.

> Fill from a confirmed `autobaud`/capture result.

---

## 2. Enter-program-mode handshake

`UNCONFIRMED` — hypothesis H1 (from TK-x180):

```
HOST → b"PROGRAM"          (at initial baud)
RADIO → 0x16               (high-speed ack)
HOST   switches to bulk baud
RADIO → 0x06               (ACK, in program mode)
HOST → 0x02                (request ident)
RADIO → <8-byte ident>     (model prefix + 0x06 ...)
HOST → 0x06                (ack ident)
```

- Exact ident bytes for NX-3320: `TODO`.
- Whether a password/model exchange is required (H3): `TODO`.

---

## 3. Block-read command

`UNCONFIRMED` — hypothesis H1:

| Field        | Hypothesis                                  | Status        |
| ------------ | ------------------------------------------- | ------------- |
| Command char | `'R'` (0x52)                                | `UNCONFIRMED` |
| Frame        | `struct.pack(">BH", ord('R'), block_no)`    | `UNCONFIRMED` |
| Address enc. | big-endian 16-bit block number              | `UNCONFIRMED` |
| Block size   | 256 bytes                                   | `UNCONFIRMED` |
| Range        | `0x0000`–`0xBF00` (+ extended `0xC000`+)    | `UNCONFIRMED` |

Extended region (H1): command `'S'` + addr + length `0x40`, response `'X'` + 64
bytes. `UNCONFIRMED`.

---

## 4. Response framing

`UNCONFIRMED` — hypothesis H1:

```
RADIO → 'W' (0x57) + <block bytes> [+ checksum]   # data block
   or
RADIO → 'Z' (0x5A)                                # all-0xFF block, no data
HOST  → 0x06                                       # ACK, request next
```

- Is the checksum byte appended to the block on *read*, or only on write? `TODO`.
- Trailer/terminator bytes: `TODO`.

---

## 5. Integrity check (checksum / CRC)

`UNCONFIRMED`. Candidates, in order of prior-art likelihood:

1. **8-bit modular sum** over the block (`checksum.sum8`). — H1
2. **CRC-16** (CCITT/XMODEM, ARC/Modbus, etc.). — H2/H3
3. Per-block vs whole-image scope: `TODO`.

Use `nx3000 capture-parse --solve-checksum` (the `checksum.solve()` search) on a
captured block+trailer to identify the algorithm. Record the winner here with its
parameters (poly, init, refin/refout, xorout) once found.

---

## 6. ACK / NAK bytes

`UNCONFIRMED` — hypothesis: `0x06` ACK, `0x16` speed-ack, `0x15` NAK.

---

## 7. Session teardown

`UNCONFIRMED` — hypothesis: HOST → `'E'`, RADIO → `0x06`. (`'E'` is host→radio;
benign, but still gated behind `--allow-tx`.)

---

## 8. TX safety allowlist (enforced in code)

Host→radio opcodes the tool is permitted to transmit during Phase 1 (read-only),
even with `--allow-tx` set. Anything not listed is **hard-blocked** by
`protocol.SAFE_TX_OPCODES`:

| Opcode            | Meaning              | Allowed? |
| ----------------- | -------------------- | -------- |
| `b"PROGRAM"`      | enter prog mode      | ✅ safe  |
| `0x02`            | ident request        | ✅ safe  |
| `0x06`            | ACK                  | ✅ safe  |
| `'R'` (0x52)      | read block           | ✅ safe  |
| `'S'` (0x53)      | read extended block  | ✅ safe  |
| `'E'` (0x45)      | end session          | ✅ safe  |
| `'W'` (0x57)      | **write block**      | ⛔ blocked |
| `'X'` (0x58)      | **write extended**   | ⛔ blocked |
| `'Z'` (0x5A)      | **write 0xFF block** | ⛔ blocked |
| anything else     | unknown              | ⛔ blocked |

> Update this table the moment a capture confirms/contradicts an opcode. Never
> move an opcode into the "allowed" column without proof it is not a write/erase.

---

## 9. Total codeplug size

`TODO` — cross-check the reassembled length against the known NX-3000 codeplug
size during Phase 3 verification. Record the confirmed value here.
