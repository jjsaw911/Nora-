"""Parse logic-analyzer / serial-sniffer captures into a framed byte stream.

This is the workhorse of Phase 1: feed it whatever a capture produced and get
back a clean, direction-separated byte stream to iterate the spec against. Per
the owner's setup (programming cable, no dedicated logic analyzer yet), it
supports three ingest formats:

* **raw ``.bin``** — undifferentiated bytes (e.g. a one-direction dump).
* **decoded-byte CSV** — generic ``time,direction,hex/dec`` rows, the common
  shape of both sigrok ``sigrok-cli`` UART exports and software COM sniffers.
* **timestamped serial-sniff log** — ``time direction hexbytes`` lines.

All parsers normalise to a list of :class:`CaptureEvent` (timestamp, direction,
bytes), from which :func:`reassemble` builds per-direction byte streams. The CSV
parser is column-name tolerant so it works with logic-analyzer exports too.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Direction(Enum):
    HOST_TO_RADIO = "tx"   # host -> radio
    RADIO_TO_HOST = "rx"   # radio -> host
    UNKNOWN = "?"

    @classmethod
    def parse(cls, token: str) -> "Direction":
        t = token.strip().lower()
        if t in {"tx", "host", "host->radio", "out", "mosi", "->", "h", "send", "0"}:
            return cls.HOST_TO_RADIO
        if t in {"rx", "radio", "radio->host", "in", "miso", "<-", "r", "recv", "1"}:
            return cls.RADIO_TO_HOST
        return cls.UNKNOWN


@dataclass(frozen=True)
class CaptureEvent:
    """One decoded byte (or byte group) with optional timing/direction."""

    data: bytes
    direction: Direction = Direction.UNKNOWN
    timestamp: float | None = None


@dataclass
class Capture:
    events: list[CaptureEvent] = field(default_factory=list)
    source: str = ""

    def stream(self, direction: Direction | None = None) -> bytes:
        """Concatenate event bytes, optionally filtered to one direction."""
        return b"".join(
            ev.data for ev in self.events if direction is None or ev.direction == direction
        )

    def __len__(self) -> int:
        return sum(len(ev.data) for ev in self.events)


# ---------------------------------------------------------------------------
# Byte-token parsing helpers
# ---------------------------------------------------------------------------

_HEX_TOKEN = re.compile(r"(?:0x)?([0-9a-fA-F]{2})")


def _parse_byte_field(field_value: str) -> bytes:
    """Parse a cell that may hold one byte or several (hex, decimal, or 0x-prefixed).

    Accepts: ``"3F"``, ``"0x3f"``, ``"63"`` (decimal), ``"52 4F 4D"`` (space/comma
    separated hex run), ``"'R'"`` (quoted ASCII).
    """
    s = field_value.strip()
    if not s:
        return b""
    # Quoted ASCII char, e.g. 'R'
    if len(s) == 3 and s[0] == s[2] and s[0] in "'\"":
        return s[1].encode("latin-1")
    # A run of hex byte tokens
    tokens = re.split(r"[\s,]+", s)
    if len(tokens) > 1 and all(_HEX_TOKEN.fullmatch(t) for t in tokens):
        return bytes(int(t.replace("0x", ""), 16) for t in tokens)
    # Single 0x-prefixed or bare hex pair
    m = _HEX_TOKEN.fullmatch(s)
    if m:
        return bytes([int(m.group(1), 16)])
    # Decimal fallback
    if s.isdigit():
        v = int(s)
        if 0 <= v <= 0xFF:
            return bytes([v])
    raise ValueError(f"cannot parse byte field: {field_value!r}")


# ---------------------------------------------------------------------------
# Format parsers
# ---------------------------------------------------------------------------


def parse_raw_bin(path: str | Path, direction: Direction = Direction.UNKNOWN) -> Capture:
    """Load a raw ``.bin`` as a single UNKNOWN-direction event stream."""
    raw = Path(path).read_bytes()
    return Capture(events=[CaptureEvent(raw, direction)], source=str(path))


# Column-name candidates we recognise in CSV headers (case-insensitive).
_TIME_COLS = ("time", "timestamp", "t", "time(s)", "time [s]")
_DIR_COLS = ("dir", "direction", "channel", "source", "label", "side")
_DATA_COLS = ("data", "byte", "value", "hex", "ascii", "decoded", "uart")


def _pick(header: list[str], candidates: tuple[str, ...]) -> int | None:
    low = [h.strip().lower() for h in header]
    for cand in candidates:
        if cand in low:
            return low.index(cand)
    return None


def parse_csv(text_or_path: str | Path, *, default_direction: Direction = Direction.UNKNOWN) -> Capture:
    """Parse a decoded-byte CSV (sigrok UART export or generic sniffer CSV).

    Tolerant of column naming and ordering. If no recognised data column is found
    it falls back to the last column. Direction is parsed from a direction column
    when present, else ``default_direction``.
    """
    if isinstance(text_or_path, (str, Path)) and Path(str(text_or_path)).exists():
        source = str(text_or_path)
        text = Path(text_or_path).read_text()
    else:
        source = "<string>"
        text = str(text_or_path)

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        return Capture(source=source)

    # Detect a header row (non-numeric first cell that names a known column).
    header = rows[0]
    has_header = any(
        h.strip().lower() in _TIME_COLS + _DIR_COLS + _DATA_COLS for h in header
    )
    data_rows = rows[1:] if has_header else rows

    t_idx = _pick(header, _TIME_COLS) if has_header else None
    d_idx = _pick(header, _DIR_COLS) if has_header else None
    b_idx = _pick(header, _DATA_COLS) if has_header else None

    events: list[CaptureEvent] = []
    for row in data_rows:
        if not row:
            continue
        data_cell = row[b_idx] if (b_idx is not None and b_idx < len(row)) else row[-1]
        try:
            data = _parse_byte_field(data_cell)
        except ValueError:
            continue  # skip undecodable rows (e.g. annotation/comment rows)
        if not data:
            continue
        direction = (
            Direction.parse(row[d_idx]) if (d_idx is not None and d_idx < len(row)) else default_direction
        )
        ts = None
        if t_idx is not None and t_idx < len(row):
            try:
                ts = float(row[t_idx])
            except ValueError:
                ts = None
        events.append(CaptureEvent(data, direction, ts))

    return Capture(events=events, source=source)


# Sniffer line, e.g.:  "0.012345  TX  50 52 4F 47"  or  "[12.3ms] RX: 06"
_SNIFF_LINE = re.compile(
    r"^\s*(?:\[?\s*(?P<ts>[\d.]+)\s*(?:ms|s)?\]?)?\s*"
    r"(?P<dir>TX|RX|HOST|RADIO|IN|OUT|->|<-)?\s*[:=]?\s*"
    r"(?P<bytes>(?:(?:0x)?[0-9a-fA-F]{2}[\s,]*)+)\s*$",
    re.IGNORECASE,
)


def parse_sniff_log(text_or_path: str | Path) -> Capture:
    """Parse a timestamped serial-sniff text log into a Capture.

    Each recognised line contributes one event; unrecognised lines are skipped so
    free-form headers/comments in a sniffer dump don't break parsing.
    """
    if isinstance(text_or_path, (str, Path)) and Path(str(text_or_path)).exists():
        source = str(text_or_path)
        text = Path(text_or_path).read_text()
    else:
        source = "<string>"
        text = str(text_or_path)

    events: list[CaptureEvent] = []
    for line in text.splitlines():
        m = _SNIFF_LINE.match(line)
        if not m:
            continue
        try:
            data = _parse_byte_field(m.group("bytes"))
        except ValueError:
            continue
        if not data:
            continue
        direction = Direction.parse(m.group("dir") or "")
        ts = float(m.group("ts")) if m.group("ts") else None
        events.append(CaptureEvent(data, direction, ts))
    return Capture(events=events, source=source)


# ---------------------------------------------------------------------------
# Dispatch + reassembly
# ---------------------------------------------------------------------------


def load(path: str | Path) -> Capture:
    """Auto-dispatch by file extension. ``.bin`` raw, ``.csv`` CSV, else sniff log."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".bin":
        return parse_raw_bin(p)
    if suffix == ".csv":
        return parse_csv(p)
    return parse_sniff_log(p)


@dataclass(frozen=True)
class Reassembly:
    tx: bytes        # host -> radio
    rx: bytes        # radio -> host
    combined: bytes  # all events in capture order (direction-agnostic)


def reassemble(capture: Capture) -> Reassembly:
    """Split a capture into host/radio byte streams plus a combined stream."""
    return Reassembly(
        tx=capture.stream(Direction.HOST_TO_RADIO),
        rx=capture.stream(Direction.RADIO_TO_HOST),
        combined=capture.stream(None),
    )


def hexdump(data: bytes, width: int = 16) -> str:
    """Compact hexdump for logging captured bytes into docs/capture-log.md."""
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{off:08x}  {hexpart:<{width * 3}}  {asciipart}")
    return "\n".join(lines)
