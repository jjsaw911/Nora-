"""NXDN channel-number <-> RF frequency mapping.

NXDN channel grants on the control channel reference a *channel number*, not a
frequency. The mapping is system-specific, so the practical approach (the one
DSD-FME uses) is a CSV lookup table::

    channel(dec), freq(Hz)
    141,423862500
    142,424337500

Some systems are regular enough to be described by a base frequency + step, so
this class also supports a linear fallback for channels not in the table.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union


@dataclass
class ChannelMap:
    """Channel-number to frequency map with an optional linear fallback."""

    table: Dict[int, int] = field(default_factory=dict)
    base_freq_hz: Optional[int] = None
    base_channel: int = 0
    step_hz: int = 0

    @classmethod
    def from_csv(cls, path: Union[str, Path]) -> "ChannelMap":
        """Load a ``channel(dec), freq(Hz)`` CSV (header optional)."""
        table: Dict[int, int] = {}
        with open(path, newline="") as fh:
            for row in csv.reader(fh):
                if not row or len(row) < 2:
                    continue
                chan_s, freq_s = row[0].strip(), row[1].strip()
                if not chan_s or not chan_s.lstrip("-").isdigit():
                    continue  # skip header / comment rows
                table[int(chan_s)] = int(freq_s)
        return cls(table=table)

    def freq_for(self, channel: int) -> Optional[int]:
        """Return the frequency (Hz) for ``channel``, or ``None`` if unknown."""
        if channel in self.table:
            return self.table[channel]
        if self.base_freq_hz is not None and self.step_hz:
            return self.base_freq_hz + (channel - self.base_channel) * self.step_hz
        return None

    def channel_for(self, freq_hz: int, tol_hz: int = 1) -> Optional[int]:
        """Reverse lookup: nearest channel within ``tol_hz`` of ``freq_hz``."""
        best: Optional[int] = None
        best_err = tol_hz + 1
        for chan, f in self.table.items():
            err = abs(f - freq_hz)
            if err <= tol_hz and err < best_err:
                best, best_err = chan, err
        return best

    def __len__(self) -> int:
        return len(self.table)
