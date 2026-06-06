# Networked SDR — Android client

Thin client for the Pi SDR server (`../pi-server`). It sends control commands
over REST, plays the demodulated PCM audio from `/ws/audio`, and renders a
scrolling waterfall + spectrum line from `/ws/spectrum`. **No SDR DSP runs on
the phone.**

## Stack
- Kotlin, Jetpack Compose (Material 3), **minSdk 26 / targetSdk 35**
- OkHttp for REST + WebSocket
- `AudioTrack` (streaming mode) for PCM playback with a jitter buffer
- Compose `Canvas` for the spectrum line + a scrolling `Bitmap` waterfall
- DataStore for persisted settings

## Build & install

```bash
cd android
# point at your SDK (or set ANDROID_HOME / sdk.dir in local.properties)
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb logcat -s NetworkedSDR:*    # watch the connection + audio pipeline
```

All connection/audio logging is tagged **`NetworkedSDR`** and is intentionally
verbose so the operator can confirm what the pipeline is doing (socket open /
close / reconnect, negotiated audio format, jitter-buffer prime, underruns).

## Using it
1. **Settings** (top-right): enter the Pi's host/IP and port (default 8080),
   tap **Save**. Persisted via DataStore.
2. **Connect** on the main screen. The app opens both WebSockets, starts audio,
   and pushes your last-used frequency/mode/gain/squelch to the server.
3. Enter a **frequency** (MHz) and tap **Tune**, pick a **mode** (WBFM/NBFM/AM),
   adjust **gain** (or Auto), **squelch**, and **volume**.
4. The **waterfall** scrolls in real time with a spectrum line on top. **Tap the
   waterfall to tune** to that point in the span.

Both sockets **auto-reconnect** with exponential backoff (1→16 s); the status
chip in the top bar shows connecting / connected / reconnecting / offline.

## Architecture
```
MainActivity.kt     Compose UI: main + settings screens, connection chip
MainViewModel.kt    orchestration; persists settings; polls /status @1Hz
net/SdrClient.kt    OkHttp REST + audio/spectrum WebSockets, auto-reconnect
audio/AudioPlayer.kt AudioTrack streaming + jitter buffer (mute on underrun)
ui/Waterfall.kt     scrolling Bitmap waterfall + spectrum line + tap-to-tune
ui/Theme.kt         Material 3 theme
data/SettingsStore.kt  DataStore-backed AppSettings
```

> You can build/install the app, but RF reception can only be confirmed on a
> real device with the Pi + dongle running — watch `adb logcat -s NetworkedSDR:*`
> and report what the logs show.
