"""Dual-dongle NXDN trunk follower.

Classic two-receiver trunk-tracking: dongle A ("control") stays parked on the
control channel decoding CAC grants; dongle B ("voice") is retuned to whatever
voice channel was just granted and follows the call until it ends, then parks
again so the next grant can be caught immediately.

This module is pure control logic — it takes decoded control-channel *events*
and a :class:`nora_nxdn.channelmap.ChannelMap`, and drives an SDR source's
``tune()``. That keeps it fully testable with a fake clock and a
:class:`nora_nxdn.sdr.FakeSource` (no hardware required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from .channelmap import ChannelMap
from .sdr import SdrSource


class State(Enum):
    IDLE = "IDLE"
    FOLLOWING = "FOLLOWING"


@dataclass(frozen=True)
class Grant:
    """A voice-channel grant decoded from the control channel."""

    channel: int
    talkgroup: Optional[int] = None
    source: Optional[int] = None


@dataclass
class TrunkController:
    """Drive the voice dongle in response to control-channel grants.

    Args:
        voice_sdr: the SDR source to retune onto granted voice channels.
        channel_map: channel-number -> frequency lookup.
        hangtime_s: how long to keep following after the last activity before
            returning to idle.
        parking_freq_hz: optional frequency to park the voice dongle on when
            idle (e.g. a secondary control channel). ``None`` leaves it put.
        allow_talkgroups: optional whitelist; grants for other talkgroups are
            ignored. ``None`` follows everything.
        clock: monotonic time source (seconds); injectable for tests.
        on_event: optional callback(str, dict) for logging/telemetry.
    """

    voice_sdr: SdrSource
    channel_map: ChannelMap
    hangtime_s: float = 3.0
    parking_freq_hz: Optional[int] = None
    allow_talkgroups: Optional[List[int]] = None
    clock: Callable[[], float] = field(default=None)  # type: ignore[assignment]
    on_event: Optional[Callable[[str, dict], None]] = None

    state: State = field(default=State.IDLE, init=False)
    current: Optional[Grant] = field(default=None, init=False)
    _last_activity: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.clock is None:
            import time

            self.clock = time.monotonic

    # -- internal helpers ---------------------------------------------------
    def _emit(self, kind: str, **data) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _wanted(self, grant: Grant) -> bool:
        if self.allow_talkgroups is None or grant.talkgroup is None:
            return True
        return grant.talkgroup in self.allow_talkgroups

    # -- public API ---------------------------------------------------------
    def on_grant(self, grant: Grant) -> bool:
        """Handle a decoded grant. Returns ``True`` if the voice dongle moved."""
        if not self._wanted(grant):
            self._emit("grant_ignored", channel=grant.channel, tg=grant.talkgroup)
            return False

        freq = self.channel_map.freq_for(grant.channel)
        if freq is None:
            self._emit("grant_no_freq", channel=grant.channel)
            return False

        moved = self.current is None or self.current.channel != grant.channel
        if moved:
            self.voice_sdr.tune(freq)
            self._emit(
                "follow", channel=grant.channel, freq=freq, tg=grant.talkgroup
            )
        self.current = grant
        self.state = State.FOLLOWING
        self._last_activity = self.clock()
        return moved

    def on_voice_activity(self) -> None:
        """Note ongoing voice on the followed channel (resets the hangtimer)."""
        if self.state is State.FOLLOWING:
            self._last_activity = self.clock()

    def on_call_end(self) -> None:
        """Explicit end-of-call signalling: return to idle immediately."""
        self._return_to_idle("call_end")

    def tick(self) -> None:
        """Call periodically: expire a stale follow after the hangtime."""
        if self.state is State.FOLLOWING:
            if self.clock() - self._last_activity >= self.hangtime_s:
                self._return_to_idle("hangtime")

    def _return_to_idle(self, reason: str) -> None:
        if self.state is State.IDLE:
            return
        self.state = State.IDLE
        prev = self.current
        self.current = None
        if self.parking_freq_hz is not None:
            self.voice_sdr.tune(self.parking_freq_hz)
        self._emit(
            "idle",
            reason=reason,
            channel=prev.channel if prev else None,
        )
