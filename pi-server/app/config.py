"""Static configuration, capabilities, and runtime defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .dsp import AUDIO_RATE


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Settings:
    """Server-wide settings, overridable via environment variables."""

    host: str = os.environ.get("SDR_HOST", "0.0.0.0")
    port: int = _env_int("SDR_PORT", 8080)

    # Default tuning / DSP parameters.
    sample_rate: int = _env_int("SDR_SAMPLE_RATE", 2_048_000)
    center_hz: int = _env_int("SDR_CENTER_HZ", 96_900_000)
    mode: str = os.environ.get("SDR_MODE", "wbfm")
    squelch_db: float = _env_float("SDR_SQUELCH_DB", -40.0)
    audio_rate: int = AUDIO_RATE

    # gain may be a float (dB) or the string "auto".
    gain_db: object = os.environ.get("SDR_GAIN", "auto")

    # Force the synthetic source even if a dongle is present (handy for CI/dev).
    force_mock: bool = os.environ.get("SDR_FORCE_MOCK", "0") not in ("0", "", "false", "False")

    # Capabilities advertised on /config.
    supported_modes: list[str] = field(default_factory=lambda: ["wbfm", "nbfm", "am"])
    supported_sample_rates: list[int] = field(
        default_factory=lambda: [2_048_000, 1_024_000]
    )
    # RTL-SDR (R820T) tuning range, Hz.
    freq_min_hz: int = 24_000_000
    freq_max_hz: int = 1_766_000_000

    def __post_init__(self) -> None:
        if isinstance(self.gain_db, str) and self.gain_db not in ("auto",):
            try:
                self.gain_db = float(self.gain_db)
            except ValueError:
                self.gain_db = "auto"


settings = Settings()
