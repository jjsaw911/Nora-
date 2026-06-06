"""Radio engine: owns the SDR, runs the DSP loop, fans frames out to clients.

Design notes (from the brief):

* A single worker *thread* performs the blocking USB read and all DSP, so the
  asyncio event loop is never blocked on the dongle.
* Frames are handed to per-client ``asyncio.Queue``s. Each queue is bounded;
  when a slow client fills it we **drop the oldest** frame and keep the newest.
  Spectrum queues are depth-1 so the client always gets the freshest FFT.
* All device mutations (tune/gain/mode/rate) are funneled through a thread-safe
  command queue and applied inside the worker, so only one thread ever touches
  the SDR.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time

import numpy as np

from .config import Settings
from .dsp import AUDIO_RATE, Spectrum, make_demodulator
from .sdr import open_source

log = logging.getLogger("NetworkedSDR.radio")

SPECTRUM_FPS = 15.0
BLOCK_SECONDS = 0.04  # ~40 ms audio frames


class Radio:
    def __init__(self, settings: Settings):
        self.s = settings
        self.center_hz = settings.center_hz
        self.mode = settings.mode
        self.gain_db = settings.gain_db
        self.sample_rate = settings.sample_rate
        self.squelch_db = settings.squelch_db
        self.audio_rate = AUDIO_RATE
        self.running = False

        self._source = None
        self._demod = None
        self._spectrum = Spectrum()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._commands: "queue.Queue[tuple[str, object]]" = queue.Queue()

        self._audio_subs: set[asyncio.Queue] = set()
        self._spectrum_subs: set[asyncio.Queue] = set()

        self._last_audio_db = -120.0

    # ----------------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------------- #
    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sdr-dsp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._source:
            self._source.close()
        self.running = False

    # ----------------------------------------------------------------- #
    # Subscriptions (called from the event-loop thread)
    # ----------------------------------------------------------------- #
    def subscribe_audio(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._audio_subs.add(q)
        return q

    def unsubscribe_audio(self, q: asyncio.Queue) -> None:
        self._audio_subs.discard(q)

    def subscribe_spectrum(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._spectrum_subs.add(q)
        return q

    def unsubscribe_spectrum(self, q: asyncio.Queue) -> None:
        self._spectrum_subs.discard(q)

    # ----------------------------------------------------------------- #
    # Commands (thread-safe; applied inside the worker)
    # ----------------------------------------------------------------- #
    def tune(self, freq_hz: float) -> None:
        self._commands.put(("tune", float(freq_hz)))

    def set_gain(self, gain_db) -> None:
        self._commands.put(("gain", gain_db))

    def set_mode(self, mode: str) -> None:
        self._commands.put(("mode", str(mode)))

    def set_sample_rate(self, rate: float) -> None:
        self._commands.put(("rate", float(rate)))

    def set_squelch(self, db: float) -> None:
        self._commands.put(("squelch", float(db)))

    def status(self) -> dict:
        return {
            "center_hz": self.center_hz,
            "mode": self.mode,
            "gain_db": self.gain_db,
            "sample_rate": self.sample_rate,
            "audio_rate": self.audio_rate,
            "squelch_db": self.squelch_db,
            "running": self.running,
            "mock": bool(self._source.is_mock) if self._source else None,
            "signal_db": round(self._last_audio_db, 1),
        }

    # ----------------------------------------------------------------- #
    # Worker thread
    # ----------------------------------------------------------------- #
    def _apply_commands(self) -> None:
        while True:
            try:
                cmd, val = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if cmd == "tune":
                    self._source.center_freq = val
                    self.center_hz = int(val)
                    log.info("tuned -> %.0f Hz", val)
                elif cmd == "gain":
                    self._source.set_gain(val)
                    self.gain_db = val
                    log.info("gain -> %s", val)
                elif cmd == "mode":
                    self.mode = val
                    self._demod = make_demodulator(val, self.sample_rate, self.squelch_db)
                    log.info("mode -> %s", val)
                elif cmd == "rate":
                    self._source.sample_rate = val
                    self.sample_rate = int(self._source.sample_rate)
                    self._demod = make_demodulator(self.mode, self.sample_rate, self.squelch_db)
                    log.info("sample_rate -> %d", self.sample_rate)
                elif cmd == "squelch":
                    self.squelch_db = val
                    if hasattr(self._demod, "squelch_db"):
                        self._demod.squelch_db = val
                    log.info("squelch -> %.1f dB", val)
            except Exception:  # noqa: BLE001
                log.exception("failed to apply command %s=%s", cmd, val)

    def _run(self) -> None:
        self._source = open_source(
            self.sample_rate, self.center_hz, self.gain_db, force_mock=self.s.force_mock
        )
        self.sample_rate = int(self._source.sample_rate)
        self.center_hz = int(self._source.center_freq)
        self._demod = make_demodulator(self.mode, self.sample_rate, self.squelch_db)
        self.running = True

        last_spectrum = 0.0
        spectrum_period = 1.0 / SPECTRUM_FPS
        log.info("DSP loop started (fs=%d, mode=%s)", self.sample_rate, self.mode)

        while not self._stop.is_set():
            self._apply_commands()
            block = int(self.sample_rate * BLOCK_SECONDS)
            try:
                iq = self._source.read(block)
            except Exception:  # noqa: BLE001
                log.exception("SDR read failed; retrying")
                time.sleep(0.2)
                continue

            # --- audio path ---
            try:
                audio = self._demod.process(iq)
            except Exception:  # noqa: BLE001
                log.exception("demod failed")
                audio = np.zeros(0, dtype=np.float32)
            if len(audio):
                rms = float(np.sqrt(np.mean(audio ** 2))) + 1e-12
                self._last_audio_db = 20.0 * np.log10(rms)
                pcm = self._to_pcm(audio)
                self._publish(self._audio_subs, pcm)

            # --- spectrum path (rate-limited) ---
            now = time.time()
            if now - last_spectrum >= spectrum_period and self._spectrum_subs:
                last_spectrum = now
                frame = self._spectrum.compute(iq)
                self._publish(self._spectrum_subs, frame)

        log.info("DSP loop stopped")

    @staticmethod
    def _to_pcm(audio: np.ndarray) -> bytes:
        clipped = np.clip(audio, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes()

    def _publish(self, subs: set[asyncio.Queue], item: bytes) -> None:
        """Push ``item`` to every subscriber from the worker thread.

        Bounded queues with drop-oldest backpressure: a slow client never grows
        memory without bound and always converges on the freshest frame.
        """
        if not subs or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._deliver, list(subs), item)

    @staticmethod
    def _deliver(subs: list[asyncio.Queue], item: bytes) -> None:
        for q in subs:
            if q.full():
                try:
                    q.get_nowait()  # drop oldest
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass
