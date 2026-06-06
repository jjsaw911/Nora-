#!/usr/bin/env python3
"""Entry point: ``python run.py`` (or ``python -m app``) starts the server.

Env vars (see app/config.py): SDR_HOST, SDR_PORT, SDR_SAMPLE_RATE, SDR_CENTER_HZ,
SDR_MODE, SDR_GAIN, SDR_SQUELCH_DB, SDR_FORCE_MOCK=1 to run without a dongle.
"""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="info")
