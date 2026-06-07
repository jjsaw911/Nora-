# Architecture

```
                 ┌──────────────┐   IQ    ┌─────────────────────────────┐
 RTL-SDR #1 ───► │ sdr.py        │ ──────► │ dsp.Demodulator             │
 (control ch.)   │ RtlSdrIqSource│         │  FM discriminator           │
                 └──────────────┘         │  → RRC matched filter        │
                                          │  → Gardner symbol recovery   │
                                          │  → 4-level slicer            │
                                          └──────────────┬──────────────┘
                                                         │ dibits
                                                         ▼
                                          ┌─────────────────────────────┐
                                          │ framing.find_sync            │  ← sign-only
                                          │  (FSW correlation)           │     FSW match
                                          └──────────────┬──────────────┘
                                                         │ frame boundary + type
                                                         ▼
                              ┌────────────────┐   ┌──────────────────────┐
                              │ scramble.py    │──►│ lich.decode_lich     │
                              │ PN95 descramble│   │  (burst classify)    │
                              └────────────────┘   └──────────┬───────────┘
                                                              │
                              ┌───────────────────────────────┼───────────────┐
                              ▼                               ▼               ▼
                       SACCH / CAC                       voice frames      FACCH
                       (signalling,                      (AMBE+2) ──► external vocoder
                        channel grants)                                  (mbelib / DSD /
                              │                                            AMBE dongle)
                              ▼
                 ┌──────────────────────────┐    tune()   ┌──────────────┐
                 │ trunk.TrunkController     │ ──────────► │ RTL-SDR #2   │
                 │ (follow grants, hangtime) │             │ (voice ch.)  │
                 └──────────────────────────┘             └──────────────┘
```

## Layers

| Module | Responsibility | Tested without HW? |
| --- | --- | --- |
| `dsp.py` | IQ → soft symbols → dibits (FM discriminator, RRC matched filter, Gardner TED, 4-level slicer) | ✅ synthetic IQ |
| `framing.py` | Frame-sync-word detection via DSD-style sign correlation; burst typing | ✅ |
| `scramble.py` | PN95 dibit (de)scrambler (self-inverse LFSR) | ✅ |
| `lich.py` | LICH parse + parity + burst-type table | ✅ |
| `deinterleave.py` | Block (de)interleave maps; AMBE interleave schedule | ✅ |
| `channelmap.py` | Channel-number ↔ frequency (CSV + linear fallback) | ✅ |
| `sdr.py` | RTL-SDR sources (`rtl_sdr` live, IQ-file replay, fake for tests) | ✅ (fake/file) |
| `trunk.py` | Dual-dongle follow logic (grants, hangtime, talkgroup filter) | ✅ fake clock + source |
| `cli.py` | `decode` / `trunk` / `info` entry points | n/a |

## What is intentionally *not* here

- **Voice audio / AMBE+2 vocoder.** NXDN voice is AMBE+2, which is patent-
  encumbered and proprietary. This package extracts and de-interleaves voice
  frames but hands them to an external vocoder. The clean reference path is to
  pipe to `dsd`/`dsd-fme` (which link `mbelib`) or to an AMBE hardware dongle.
- **Full FEC / Viterbi trellis decode** of SACCH/FACCH/CAC payloads is stubbed
  at the de-interleave boundary; the framing, scrambling, interleave maps and
  LICH typing are complete and tested. Wiring a convolutional decoder (K=5,
  rate-1/2 punctured, per the NXDN TS) on top of `deinterleave` is the next
  step and slots in cleanly after `framing` + `scramble`.

## Live trunking loop (two dongles)

1. Dongle #1 stays on the **control channel**; its dibit stream is framed and
   any CAC burst that carries a voice-call grant becomes a `trunk.Grant`.
2. `TrunkController.on_grant` looks the granted **channel number** up in the
   `ChannelMap` and retunes **dongle #2** to that frequency.
3. Voice activity on dongle #2 calls `on_voice_activity()` to keep the follow
   alive; an end-of-call or `hangtime_s` of silence returns dongle #2 to its
   parking frequency so the next grant is caught immediately.

The controller is pure logic (injectable clock + SDR source), so the whole
follow/hangtime/whitelist behaviour is unit-tested in `tests/test_trunk.py`
without any radio attached.
