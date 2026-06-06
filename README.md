# Networked SDR

A Raspberry Pi hosts an RTL-SDR dongle and does **all** the DSP, exposing a
small HTTP + WebSocket API. The Android app is a **thin client**: it sends
control commands, plays the demodulated audio stream, and draws a waterfall from
FFT frames the Pi sends. No SDR DSP happens on the phone.

This split keeps bandwidth low (~30–400 kbps instead of ~38 Mbps of raw IQ), so
it works over the internet, not just the LAN.

```
   RTL-SDR ──USB──> Raspberry Pi ──HTTP/WS──> Android app
                    (FastAPI + DSP)            (thin client)
                  REST control plane          plays PCM audio,
                  /ws/audio  (PCM 24k)         draws waterfall
                  /ws/spectrum (1024-bin FFT)
```

## Repo layout
```
pi-server/    FastAPI server: DSP, REST + WebSocket API, test clients   (Part A)
android/      Kotlin/Compose thin client                                (Part B)
ssh/, keys/, tunnel.sh   SSH tunnel helpers for reaching a remote Pi
```

## Run the Pi server
```bash
cd pi-server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                 # http://0.0.0.0:8080

# No dongle? Run the synthetic source (audio tone + waterfall carriers):
SDR_FORCE_MOCK=1 python run.py
```
Hardware setup (blacklisting the kernel DVB-T driver, `rtl_test`, sample-rate
notes) and the full API reference are in **[pi-server/README.md](pi-server/README.md)**.

Verify without a phone:
- `bash pi-server/tests/curl_examples.sh` — drive the control API.
- open `http://<pi>:8080/test/audio` — hear the stream in a browser.
- open `http://<pi>:8080/test/waterfall` — live waterfall in a browser.

## Run the Android client
```bash
cd android
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb logcat -s NetworkedSDR:*
```
In the app: **Settings** → enter the Pi host/port → **Connect** → tune. Details
in **[android/README.md](android/README.md)**.

## Build order (vertical slices)
- **M1** Pi audio path — WBFM → PCM over `/ws/audio`. ✅
- **M2** Control API — `/tune` `/gain` `/mode` `/squelch`. ✅
- **M3** Spectrum path — 1024-bin FFT over `/ws/spectrum`. ✅
- **M4** Android core — connect, play audio, change freq/gain/mode. ✅
- **M5** Android waterfall — scrolling spectrum + line. ✅
- **M6** Polish — squelch, NBFM/AM, auto-reconnect, persisted settings,
  tap-to-tune. ✅

M1–M3 are fully testable on the Pi/laptop with the browser + curl clients (and
the bundled mock source) — no phone required. M4+ needs a device on `adb`; RF
reception is confirmed by the human operator.

## Remote access (optional)

If the Pi lives behind the `nora` remote box, `tunnel.sh` / `ssh/config` forward
a local port to it so the app/test pages can reach `localhost:8080`:

```sh
./tunnel.sh --tunnel-only      # forward local 8080 -> remote localhost:8080
```
See the connection details and key-authorization steps in
[ssh/config](ssh/config) and `tunnel.sh`.

## Non-goals (v1)
One stream at a time; no transmit, recording, or extra decoders (ADS-B/POCSAG).
Raw PCM audio for now (Opus is a documented TODO). The phone never touches the
USB dongle — the Pi owns it.
