# Nora NXDN

A clean-room **NXDN decoder for macOS + RTL-SDR**, written in Python. It
reverse-engineers the on-air format the way [DSD](https://github.com/szechyjs/dsd)
does — frame sync, LICH, scrambling, interleaving, channel grants — and is
built for a **two-dongle trunk-tracking** setup (one stick on the control
channel, one following voice).

The DSP and protocol layers are fully unit-tested against synthetic signals, so
the whole thing builds and passes its 46 tests **with no radio attached**.

```
$ nora-nxdn decode --iq-file capture.cu8 --sample-rate 240000 --symbol-rate 4800
sync=BS_VOICE pol=norm lich=0x36 parity=ok off=8/8 :: Voice in both half-slots
sync=BS_VOICE pol=norm lich=0x36 parity=ok off=8/8 :: Voice in both half-slots
```

## What it does

- **Demodulate** 4FSK NXDN from RTL-SDR IQ: FM discriminator → RRC matched
  filter → Gardner symbol-clock recovery → 4-level slicer.
- **Frame sync** via DSD-style sign-only FSW correlation (BS/MS, voice/data,
  polarity-inverted), with fuzzy tolerance.
- **LICH** decode: parity check + burst classification (voice/FACCH/SACCH/CAC,
  half-slot stealing, inbound vs outbound).
- **PN95 descrambling** and **block de-interleaving** (the DSD/OP25 maps).
- **Dual-dongle trunk following**: park on the control channel, retune the
  second dongle to granted voice channels, hangtime + talkgroup whitelist.

## What it does *not* do (by design)

- **No voice audio.** NXDN voice is the proprietary AMBE+2 vocoder. This tool
  extracts and de-interleaves voice frames but hands them to an external
  decoder (`mbelib`/`dsd`/an AMBE dongle). See
  [`docs/protocol-notes.md`](docs/protocol-notes.md).

## Quick start

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 46 tests, no hardware

nora-nxdn info               # show the frame sync words in use
nora-nxdn decode --serial 00000001 --freq 451000000 \
                 --sample-rate 240000 --symbol-rate 4800
```

Full Mac setup (Homebrew `librtlsdr`, per-dongle serials, trunking) is in
[`docs/macos-setup.md`](docs/macos-setup.md).

## Two-dongle trunk following

```sh
nora-nxdn trunk --channel-map examples/nxdn_chan_map.csv \
                --control-freq 423862500 \
                --control-device 0 --voice-device 1 --hangtime 3.0
```

Dongle 0 camps on the control channel; dongle 1 follows each granted voice
channel. Architecture diagram: [`docs/architecture.md`](docs/architecture.md).

## Layout

```
nora_nxdn/        the package
  dsp.py            IQ → symbols (discriminator, RRC, Gardner, slicer)
  framing.py        frame-sync-word detection + burst typing
  lich.py           LICH parse + burst classification
  scramble.py       PN95 dibit (de)scrambler
  deinterleave.py   block interleave maps + AMBE schedule
  channelmap.py     channel-number ↔ frequency
  sdr.py            rtl_sdr / IQ-file / fake sources
  trunk.py          dual-dongle follow controller
  cli.py            decode / trunk / info
tests/            46 tests (synthetic signals, fake SDR + clock)
docs/             setup, architecture, protocol notes, ssh-tunnel
examples/         sample NXDN channel map
```

## Attribution & license

`nora-nxdn` is GPL-3.0-or-later. Its NXDN constants are derived from the DSD /
DSD-FME / OP25 projects; see [`NOTICE.md`](NOTICE.md) for exact provenance and
[`LICENSE`](LICENSE) for terms.

## Legal

Decode only traffic you are permitted to receive in your jurisdiction. This is
a protocol/educational tool for unencrypted, lawfully-receivable signals.

---

> The original Nora **SSH tunnel** helper now lives in
> [`docs/ssh-tunnel.md`](docs/ssh-tunnel.md) (`tunnel.sh`, `ssh/config`, and
> `keys/` are unchanged).
