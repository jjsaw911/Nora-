# macOS setup (Apple Silicon & Intel) — two RTL-SDR dongles

## 1. Install the SDR tooling

```sh
brew install librtlsdr      # provides rtl_sdr, rtl_fm, rtl_test, rtl_eeprom
brew install python@3.11
```

Verify the dongles are seen:

```sh
rtl_test -t
```

> On Apple Silicon, if `rtl_test` can't claim the device, make sure no other
> process (SDR++, GQRX, CubicSDR) has it open, and that you launched from a
> terminal with USB access.

## 2. Give each dongle a unique serial

The trunk follower addresses dongles by serial so the *control* and *voice*
roles are stable across reboots/replug. Set them once:

```sh
# With ONLY the first dongle plugged in:
rtl_eeprom -d 0 -s 00000001
# Replug, then with ONLY the second:
rtl_eeprom -d 0 -s 00000002
```

Now `--serial 00000001` always means the same physical stick.

## 3. Install nora-nxdn

```sh
git clone https://github.com/jjsaw911/nora-.git
cd nora-
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest          # 46 tests, no hardware needed
```

## 4. Decode a single NXDN channel (one dongle)

```sh
# 12.5 kHz NXDN (9600 bps / 4800 baud):
nora-nxdn decode --serial 00000001 --freq 451000000 \
                 --sample-rate 240000 --symbol-rate 4800

# 6.25 kHz NXDN (4800 bps / 2400 baud):
nora-nxdn decode --serial 00000001 --freq 451000000 \
                 --sample-rate 240000 --symbol-rate 2400
```

Tips:
- Decimation/sample-rate: 240 kHz divides cleanly and gives whole-number
  samples-per-symbol after the front end. 1.2 Msps also works.
- Use `--gain` to pin the tuner gain (auto-gain can hunt). Start ~30–40 dB.
- `--ppm` corrects the dongle's crystal error (find it with `rtl_test -p`).

## 5. Record a capture for offline work

```sh
rtl_sdr -f 451000000 -s 240000 -g 38 -d 0 capture.cu8
nora-nxdn decode --iq-file capture.cu8 --sample-rate 240000 --symbol-rate 4800
```

## 6. Two-dongle trunk following

Build a channel map CSV for your system (see `examples/nxdn_chan_map.csv`):

```csv
channel(dec), freq(Hz)
141,423862500
142,424337500
```

```sh
nora-nxdn trunk --channel-map mysystem.csv \
                --control-freq 423862500 \
                --control-device 0 --voice-device 1 \
                --hangtime 3.0
```

Dongle 0 camps on the control channel; dongle 1 retunes to each granted voice
channel and follows the call. See `docs/architecture.md` for the loop.

## 7. Voice audio (AMBE+2)

This decoder does **not** include a vocoder. To hear voice, pipe the discriminator
output to `dsd`/`dsd-fme` (built with `mbelib`) or feed extracted AMBE frames to
an AMBE-3000 hardware dongle. See `docs/protocol-notes.md`.

## Legal note

Decode only what you are licensed/permitted to receive in your jurisdiction.
Many systems are encrypted and/or protected; this tool is for the unencrypted,
lawfully-receivable traffic and for protocol education/research.
