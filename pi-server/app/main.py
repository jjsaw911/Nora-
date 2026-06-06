"""FastAPI application: REST control plane + audio/spectrum WebSockets."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, field_validator

from .config import settings
from .dsp import Spectrum
from .radio import Radio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("NetworkedSDR.api")

radio = Radio(settings)
TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"


@asynccontextmanager
async def lifespan(app: FastAPI):
    radio.start(asyncio.get_running_loop())
    log.info("server up on %s:%d", settings.host, settings.port)
    try:
        yield
    finally:
        radio.stop()


app = FastAPI(title="Networked SDR", version="0.1.0", lifespan=lifespan)

# Permissive CORS for dev so browser test pages on any origin can hit the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class TuneBody(BaseModel):
    freq_hz: float

    @field_validator("freq_hz")
    @classmethod
    def _range(cls, v: float) -> float:
        if not (settings.freq_min_hz <= v <= settings.freq_max_hz):
            raise ValueError(
                f"freq_hz out of range [{settings.freq_min_hz}, {settings.freq_max_hz}]"
            )
        return v


class GainBody(BaseModel):
    gain_db: object

    @field_validator("gain_db")
    @classmethod
    def _valid(cls, v):
        if v == "auto":
            return v
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError("gain_db must be a number or 'auto'")


class ModeBody(BaseModel):
    mode: str

    @field_validator("mode")
    @classmethod
    def _supported(cls, v: str) -> str:
        v = v.lower()
        if v not in settings.supported_modes:
            raise ValueError(f"mode must be one of {settings.supported_modes}")
        return v


class SquelchBody(BaseModel):
    db: float


# --------------------------------------------------------------------------- #
# REST control plane
# --------------------------------------------------------------------------- #
@app.get("/status")
async def get_status():
    return radio.status()


@app.get("/config")
async def get_config():
    return {
        "supported_modes": settings.supported_modes,
        "supported_sample_rates": settings.supported_sample_rates,
        "freq_min_hz": settings.freq_min_hz,
        "freq_max_hz": settings.freq_max_hz,
        "audio": {"codec": "pcm_s16le", "rate": radio.audio_rate, "channels": 1},
        "spectrum": {
            "bins": Spectrum.BINS,
            "db_floor": Spectrum.DB_FLOOR,
            "db_ceil": Spectrum.DB_CEIL,
            "fps": 15,
        },
    }


@app.post("/tune")
async def post_tune(body: TuneBody):
    radio.tune(body.freq_hz)
    return {"ok": True, "center_hz": int(body.freq_hz)}


@app.post("/gain")
async def post_gain(body: GainBody):
    radio.set_gain(body.gain_db)
    return {"ok": True, "gain_db": body.gain_db}


@app.post("/mode")
async def post_mode(body: ModeBody):
    radio.set_mode(body.mode)
    return {"ok": True, "mode": body.mode}


@app.post("/squelch")
async def post_squelch(body: SquelchBody):
    radio.set_squelch(body.db)
    return {"ok": True, "squelch_db": body.db}


# --------------------------------------------------------------------------- #
# WebSockets
# --------------------------------------------------------------------------- #
@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket):
    await ws.accept()
    q = radio.subscribe_audio()
    peer = ws.client.host if ws.client else "?"
    log.info("audio client connected: %s", peer)
    try:
        # First message: JSON describing the stream format.
        await ws.send_json(
            {"codec": "pcm_s16le", "rate": radio.audio_rate, "channels": 1}
        )
        while True:
            frame = await q.get()
            await ws.send_bytes(frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("audio ws error")
    finally:
        radio.unsubscribe_audio(q)
        log.info("audio client disconnected: %s", peer)


@app.websocket("/ws/spectrum")
async def ws_spectrum(ws: WebSocket):
    await ws.accept()
    q = radio.subscribe_spectrum()
    peer = ws.client.host if ws.client else "?"
    log.info("spectrum client connected: %s", peer)
    try:
        while True:
            frame = await q.get()
            await ws.send_bytes(frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("spectrum ws error")
    finally:
        radio.unsubscribe_spectrum(q)
        log.info("spectrum client disconnected: %s", peer)


# --------------------------------------------------------------------------- #
# Browser test pages (served for convenience during M1-M3)
# --------------------------------------------------------------------------- #
@app.get("/")
async def index():
    return JSONResponse(
        {
            "name": "Networked SDR",
            "test_pages": ["/test/audio", "/test/waterfall"],
            "rest": ["/status", "/config", "/tune", "/gain", "/mode", "/squelch"],
            "websockets": ["/ws/audio", "/ws/spectrum"],
        }
    )


@app.get("/test/audio")
async def test_audio_page():
    return FileResponse(TESTS_DIR / "audio.html")


@app.get("/test/waterfall")
async def test_waterfall_page():
    return FileResponse(TESTS_DIR / "waterfall.html")


if TESTS_DIR.is_dir():
    app.mount("/test-static", StaticFiles(directory=str(TESTS_DIR)), name="tests")
