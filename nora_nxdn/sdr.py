"""RTL-SDR sources.

Two interchangeable backends plus a fake one for tests:

* :class:`RtlFmSource` shells out to ``rtl_fm`` and yields demodulated audio /
  discriminator samples — simplest path, good for a single fixed channel.
* :class:`RtlSdrIqSource` shells out to ``rtl_sdr`` and yields raw complex IQ,
  which you feed to :class:`nora_nxdn.dsp.Demodulator`. This is what the
  trunk-follower retunes on the fly.
* :class:`IqFileSource` replays a recorded ``cu8``/``cs16`` IQ file offline.
* :class:`FakeSource` emits scripted IQ for tests.

Each source exposes ``tune(freq_hz)`` and an iterator of numpy blocks. A source
is identified by an RTL-SDR ``device_index`` or ``serial`` so the two dongles
can be told apart (set serials with ``rtl_eeprom -s``).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Union

import numpy as np


def _cu8_to_complex(raw: bytes) -> np.ndarray:
    """Convert interleaved unsigned-8-bit IQ (rtl_sdr default) to complex."""
    a = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
    a = (a - 127.5) / 127.5
    if a.size % 2:
        a = a[:-1]
    return a[0::2] + 1j * a[1::2]


class SdrSource:
    """Abstract SDR source interface."""

    sample_rate: float

    def tune(self, freq_hz: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def blocks(self) -> Iterator[np.ndarray]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass


@dataclass
class RtlSdrIqSource(SdrSource):
    """Raw IQ from ``rtl_sdr`` (retunable by restarting the child process)."""

    freq_hz: int = 0
    sample_rate: float = 240000.0
    gain: Optional[float] = None
    device_index: int = 0
    serial: Optional[str] = None
    ppm: int = 0
    block_size: int = 1 << 16
    _proc: Optional[subprocess.Popen] = field(default=None, init=False, repr=False)

    def _build_cmd(self) -> List[str]:
        exe = shutil.which("rtl_sdr")
        if exe is None:
            raise RuntimeError(
                "rtl_sdr not found on PATH (install librtlsdr: `brew install librtlsdr`)"
            )
        cmd = [
            exe,
            "-f", str(int(self.freq_hz)),
            "-s", str(int(self.sample_rate)),
            "-p", str(int(self.ppm)),
        ]
        if self.serial:
            cmd += ["-d", self.serial]
        else:
            cmd += ["-d", str(self.device_index)]
        if self.gain is not None:
            cmd += ["-g", str(self.gain)]
        cmd += ["-"]  # IQ to stdout
        return cmd

    def tune(self, freq_hz: int) -> None:
        self.freq_hz = int(freq_hz)
        if self._proc is not None:
            self.close()
            self._start()

    def _start(self) -> None:
        self._proc = subprocess.Popen(
            self._build_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

    def blocks(self) -> Iterator[np.ndarray]:
        if self._proc is None:
            self._start()
        assert self._proc is not None and self._proc.stdout is not None
        nbytes = self.block_size * 2  # 2 bytes (I,Q) per complex sample
        while True:
            raw = self._proc.stdout.read(nbytes)
            if not raw:
                break
            yield _cu8_to_complex(raw)

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self._proc.kill()
            self._proc = None


@dataclass
class IqFileSource(SdrSource):
    """Replay a recorded IQ file (``cu8`` unsigned-8-bit interleaved)."""

    path: Union[str, Path]
    sample_rate: float = 240000.0
    block_size: int = 1 << 16

    def tune(self, freq_hz: int) -> None:
        # A file is a fixed capture; tuning is a no-op recorded for the log.
        self.freq_hz = int(freq_hz)

    def blocks(self) -> Iterator[np.ndarray]:
        with open(self.path, "rb") as fh:
            nbytes = self.block_size * 2
            while True:
                raw = fh.read(nbytes)
                if not raw:
                    break
                yield _cu8_to_complex(raw)


@dataclass
class FakeSource(SdrSource):
    """In-memory IQ source for tests; yields pre-built complex blocks."""

    _blocks: List[np.ndarray] = field(default_factory=list)
    sample_rate: float = 240000.0
    freq_hz: int = 0
    tunes: List[int] = field(default_factory=list)

    def tune(self, freq_hz: int) -> None:
        self.freq_hz = int(freq_hz)
        self.tunes.append(int(freq_hz))

    def feed(self, iq: np.ndarray) -> None:
        self._blocks.append(np.asarray(iq, dtype=np.complex128))

    def blocks(self) -> Iterator[np.ndarray]:
        yield from self._blocks
