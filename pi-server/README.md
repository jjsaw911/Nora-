# Networked SDR — Raspberry Pi server

FastAPI server that owns an RTL-SDR dongle, does all the DSP, and exposes a thin
HTTP + WebSocket API: REST for control, one WebSocket for demodulated **audio**
(16-bit PCM, mono, 24 kHz) and one for a **spectrum** waterfall (fixed 1024-bin
uint8 frames). The Android app (see `../android`) is a thin client.

## 1. System setup (required, not optional)

```bash
sudo apt install -y rtl-sdr librtlsdr-dev

# CRITICAL: the kernel DVB-T driver grabs the dongle. Blacklist it:
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf
# then reboot, or unload it now:
sudo modprobe -r dvb_usb_rtl28xxu

# verify the dongle is visible (should list it and run WITHOUT
# "usb_claim_interface error"):
rtl_test
```

* Use a **USB 2.0** port. 2.4 MS/s is near the bus limit on a Pi, so this server
  defaults to **2.048 MS/s** and supports **1.024 MS/s** as a fallback
  (`SDR_SAMPLE_RATE=1024000`, or `POST /tune`… see below).

## 2. Install & run

```bash
cd pi-server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run.py                 # serves on 0.0.0.0:8080
```

No dongle handy? Run against a built-in **synthetic source** — a 440 Hz tone
FM-modulated onto the tuned center plus a couple of offset carriers, so audio and
the waterfall both show something:

```bash
SDR_FORCE_MOCK=1 python run.py
```

(The server also auto-falls back to the mock source if no dongle is detected.)

### Environment variables

| Var | Default | Meaning |
|---|---|---|
| `SDR_HOST` | `0.0.0.0` | bind host |
| `SDR_PORT` | `8080` | bind port |
| `SDR_SAMPLE_RATE` | `2048000` | IQ sample rate (`1024000` fallback) |
| `SDR_CENTER_HZ` | `96900000` | initial center frequency |
| `SDR_MODE` | `wbfm` | `wbfm` \| `nbfm` \| `am` |
| `SDR_GAIN` | `auto` | tuner gain dB or `auto` |
| `SDR_SQUELCH_DB` | `-40` | NBFM/AM squelch threshold |
| `SDR_FORCE_MOCK` | `0` | `1` to force the synthetic source |

## 3. API

### REST

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/status` | — | `{center_hz, mode, gain_db, sample_rate, audio_rate, squelch_db, running, mock, signal_db}` |
| GET | `/config` | — | capabilities: supported modes, sample rates, freq range, audio/spectrum format |
| POST | `/tune` | `{"freq_hz": 96900000}` | retune center |
| POST | `/gain` | `{"gain_db": 28.0}` or `{"gain_db": "auto"}` | |
| POST | `/mode` | `{"mode": "wbfm"\|"nbfm"\|"am"}` | |
| POST | `/squelch` | `{"db": -40}` | NBFM/AM |

CORS is fully permissive (dev) so browser test pages on any origin work.

### WebSockets

* **`/ws/audio`** — first message is JSON describing the format
  (`{"codec":"pcm_s16le","rate":24000,"channels":1}`), then binary PCM frames of
  ~40 ms each. Raw PCM for now; *TODO: optional Opus.*
* **`/ws/spectrum`** — binary frames at ~15 fps, **fixed 1024 bins**, each a
  `uint8`. The client reads center/span from `/status`; frames carry no header.

  **dB → byte mapping:** `db = 20·log10(|FFT|/N)`, then
  `byte = round((clip(db, −100, 0) + 100) / 100 · 255)` — so −100 dBFS → 0,
  0 dBFS → 255.

Backpressure: per-client frame queues are bounded and **drop the oldest** frame
when a client lags (spectrum queue is depth-1 — always the freshest FFT).

## 4. DSP chain

Read IQ as `complex64` (worker thread, never blocks the event loop), then:

* **WBFM:** lowpass + decimate IQ to ~256 kHz → FM discriminate
  (`angle(x[1:]·conj(x[:-1]))`) → 75 µs de-emphasis (single-pole IIR) → lowpass +
  resample to 24 kHz mono.
* **NBFM:** narrow decimate (~7 kHz channel) → discriminate → power **squelch**,
  no de-emphasis → resample to 24 kHz.
* **AM:** narrow decimate → envelope (`abs`) → DC removal → resample to 24 kHz.

All blocks are stateful (filter delay lines, decimation phase, fractional
resampler phase carried across chunks) so there are no clicks at boundaries.

## 5. Verifying M1–M3 (no phone needed)

Start the server (mock or real), then:

```bash
# M2 — control API
bash tests/curl_examples.sh

# M1 — audio: browser test page…
#   open http://localhost:8080/test/audio  -> Connect -> you hear audio
# …or a headless client:
python tests/audio_client.py ws://localhost:8080/ws/audio

# M3 — spectrum: open http://localhost:8080/test/waterfall -> Connect
#   -> live scrolling waterfall + spectrum line

# DSP unit tests
pytest tests/test_dsp.py
```

## Project layout

```
app/
  main.py     FastAPI app: REST + /ws/audio + /ws/spectrum, CORS, test pages
  radio.py    Radio engine: SDR worker thread, asyncio queues, backpressure
  dsp.py      Stateful demodulators (WBFM/NBFM/AM), resampler, spectrum
  sdr.py      RtlSdrSource (pyrtlsdr) + MockSource fallback
  config.py   settings + advertised capabilities
run.py        uvicorn entry point
tests/        curl + browser + python test clients, DSP unit tests
```
