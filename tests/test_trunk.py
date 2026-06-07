from nora_nxdn.channelmap import ChannelMap
from nora_nxdn.sdr import FakeSource
from nora_nxdn.trunk import Grant, State, TrunkController


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make_controller(**kw):
    cmap = ChannelMap(table={101: 451_000_000, 102: 451_012_500})
    voice = FakeSource()
    clock = Clock()
    ctrl = TrunkController(
        voice_sdr=voice, channel_map=cmap, clock=clock, hangtime_s=3.0, **kw
    )
    return ctrl, voice, clock


def test_grant_tunes_voice_dongle():
    ctrl, voice, _ = make_controller()
    moved = ctrl.on_grant(Grant(channel=101, talkgroup=5))
    assert moved
    assert ctrl.state is State.FOLLOWING
    assert voice.tunes == [451_000_000]


def test_repeat_grant_same_channel_does_not_retune():
    ctrl, voice, _ = make_controller()
    ctrl.on_grant(Grant(channel=101))
    moved = ctrl.on_grant(Grant(channel=101))
    assert not moved
    assert voice.tunes == [451_000_000]


def test_hangtime_returns_to_idle():
    ctrl, voice, clock = make_controller(parking_freq_hz=450_000_000)
    ctrl.on_grant(Grant(channel=101))
    clock.advance(1.0)
    ctrl.on_voice_activity()  # keeps it alive
    clock.advance(2.5)
    ctrl.tick()  # only 2.5s since last activity -> still following
    assert ctrl.state is State.FOLLOWING
    clock.advance(1.0)
    ctrl.tick()  # now 3.5s -> expire
    assert ctrl.state is State.IDLE
    assert voice.tunes[-1] == 450_000_000  # parked


def test_call_end_returns_immediately():
    ctrl, _, _ = make_controller()
    ctrl.on_grant(Grant(channel=102))
    ctrl.on_call_end()
    assert ctrl.state is State.IDLE


def test_talkgroup_whitelist():
    ctrl, voice, _ = make_controller(allow_talkgroups=[7])
    assert not ctrl.on_grant(Grant(channel=101, talkgroup=5))
    assert ctrl.state is State.IDLE
    assert ctrl.on_grant(Grant(channel=101, talkgroup=7))


def test_unknown_channel_no_freq():
    ctrl, voice, _ = make_controller()
    assert not ctrl.on_grant(Grant(channel=999))
    assert voice.tunes == []


def test_events_emitted():
    events = []
    ctrl, _, _ = make_controller()
    ctrl.on_event = lambda kind, data: events.append((kind, data))
    ctrl.on_grant(Grant(channel=101, talkgroup=5))
    ctrl.on_call_end()
    kinds = [e[0] for e in events]
    assert "follow" in kinds and "idle" in kinds
