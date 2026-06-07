# NXDN protocol notes (and constant provenance)

A compact reference for the parts of NXDN this decoder implements, and exactly
where each magic number came from. Full attribution is in `../NOTICE.md`.

## Physical layer

- **Modulation:** 4-level FSK (C4FM-like). Symbols carry 2 bits each.
- **Rates:**
  - 6.25 kHz channels — **2400 baud / 4800 bps**
  - 12.5 kHz channels — **4800 baud / 9600 bps**
- **Symbol → deviation:** four levels; this decoder uses the DSD slicer region
  convention so that **the dibit MSB equals the sign of the deviation**. That
  is what lets frame sync be detected with a cheap sign-only correlation.

## Frame Sync Word (FSW)

DSD detects the FSW by reducing each symbol to its sign (`+ → '1'`, `- → '3'`)
and matching an 18-symbol string. The four patterns (plus inverted-polarity
twins) are in `nora_nxdn/framing.py`:

| Type | Pattern (`1`=+, `3`=-) |
| --- | --- |
| MS_DATA | `313133113131111333` |
| MS_VOICE | `313133113131113133` |
| BS_DATA | `313133113131111313` |
| BS_VOICE | `313133113131113113` |

`MS` = mobile/subscriber (inbound), `BS` = base station (outbound). Source:
DSD `include/dsd.h`.

## LICH (Link Information Channel)

- 8 dibits immediately after the FSW.
- Each dibit's **MSB** is one info bit; the **LSB** is a fixed "off" bit that
  reads 1 on a clean signal (used as a confidence metric — `off_bits`).
- The 8 info bits form a byte: `code(7) << 1 | parity(1)`, parity = even over
  bits 7,6,5,4.
- The 7-bit code selects the burst layout (voice/FACCH/SACCH/CAC, which
  half-slots, inbound vs outbound). Table mirrored from DSD-FME
  `src/nxdn_frame.c` → `nora_nxdn/lich.py`.

## Scrambling — PN95

On-air dibits after the LICH are scrambled by a PN sequence from a 9-bit
Fibonacci LFSR:

- seed `0xE4` (228)
- right-shifting register; feedback `bit = ((lfsr>>4) ^ (lfsr>>0)) & 1`, fed to
  bit 8 after the shift
- where the PN bit is 1, the dibit is inverted via `dibit ^= 0x2`

Self-inverse, so the same routine scrambles and descrambles. Source: DSD-FME
`src/nxdn_deperm.c` → `nora_nxdn/scramble.py`.

## Interleaving and FEC

- Logical channels are convolutionally coded (K=5, rate-1/2, punctured) then
  **block-interleaved**. The interleave maps (`PERM_12_5`, `PERM_16_9`,
  `PERM_12_25`, `PERM_12_29`) are in `nora_nxdn/deinterleave.py` (from
  DSD-FME / OP25 `include/nxdn_const.h`).
- This package implements framing → descramble → de-interleave. The
  convolutional/Viterbi decode of the de-interleaved SACCH/FACCH/CAC payloads
  is the documented next step (see `architecture.md`); it slots in directly
  after `deinterleave`.

## Voice — AMBE+2 (out of scope, by design)

NXDN voice is **AMBE+2**, proprietary and patent-encumbered. This project does
not and will not ship a vocoder. The AMBE interleave schedule (nW/nX/nY/nZ from
DSD `include/nxdn_const.h`) is provided in `deinterleave.AMBE_SCHEDULE` so voice
frames can be correctly **de-interleaved and reassembled**, then handed to:

- `dsd` / `dsd-fme` linked against `mbelib`, or
- an AMBE-3000 hardware dongle.

## Channel grants & trunking

Control-channel CAC bursts carry voice-call grants referencing a **channel
number**, not a frequency. The number→frequency map is system-specific, so we
use a CSV table (DSD-FME's `nxdn_chan_map.csv` format) with an optional
base+step linear fallback. See `nora_nxdn/channelmap.py`.

## Further reading

- NXDN Technical Specifications (NXDN Forum) — the authoritative spec.
- DSD: <https://github.com/szechyjs/dsd>
- DSD-FME: <https://github.com/lwvmobile/dsd-fme>
- OP25: project wiki / `op25/gr-op25_repeater`.
