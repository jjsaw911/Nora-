"""Local, OpenAI-compatible speech-to-text server built on faster-whisper.

Drop-in replacement for OpenAI's paid Whisper API: apps that POST audio to
`/v1/audio/transcriptions` can point their base URL here instead and keep the
same request shape (multipart `file`, plus optional `model`, `language`,
`prompt`, `response_format`).

Configure with environment variables (setup.sh writes them to whisper.env):
    WHISPER_MODEL    e.g. large-v3-turbo (GPU) or small (CPU)
    WHISPER_DEVICE   auto | cuda | cpu
    WHISPER_COMPUTE  float16 (GPU) | int8 (CPU) | default
"""

import os
import shutil
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from faster_whisper import WhisperModel

MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "default")

# Loaded once at startup; downloads the model on first run.
model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)

app = FastAPI(title="Local Whisper")


def _timestamp(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def _subtitles(segments, vtt: bool) -> str:
    sep = "." if vtt else ","
    blocks = []
    for i, seg in enumerate(segments, start=1):
        span = f"{_timestamp(seg.start, sep)} --> {_timestamp(seg.end, sep)}"
        text = seg.text.strip()
        blocks.append(f"{span}\n{text}" if vtt else f"{i}\n{span}\n{text}")
    body = "\n\n".join(blocks) + "\n"
    return "WEBVTT\n\n" + body if vtt else body


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]}


# A plain `def` endpoint: FastAPI runs it in a worker thread, so a long
# transcription doesn't block other requests.
@app.post("/v1/audio/transcriptions")
def transcribe(
    file: UploadFile = File(...),
    model_field: str = Form("whisper-1", alias="model"),  # accepted, ignored
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str = Form("json"),
    temperature: float = Form(0.0),
):
    if response_format not in ("json", "text", "verbose_json", "srt", "vtt"):
        raise HTTPException(400, f"unsupported response_format '{response_format}'")

    suffix = os.path.splitext(file.filename or "")[1]
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        segments, info = model.transcribe(
            tmp.name,
            language=language or None,
            initial_prompt=prompt or None,
            temperature=temperature,
            vad_filter=True,  # skip silence: faster and fewer hallucinations
        )
        segments = list(segments)

    text = "".join(seg.text for seg in segments).strip()

    if response_format == "text":
        return PlainTextResponse(text)
    if response_format in ("srt", "vtt"):
        return PlainTextResponse(_subtitles(segments, vtt=response_format == "vtt"))
    if response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": info.language,
            "duration": info.duration,
            "text": text,
            "segments": [
                {"id": i, "start": s.start, "end": s.end, "text": s.text}
                for i, s in enumerate(segments)
            ],
        }
    return {"text": text}
