from pathlib import Path

from nora_nxdn.channelmap import ChannelMap

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "nxdn_chan_map.csv"


def test_load_example_csv():
    cmap = ChannelMap.from_csv(EXAMPLE)
    assert len(cmap) >= 7
    # From the example file header rows are skipped, data parsed.
    assert cmap.freq_for(141) == 423862500
    assert cmap.freq_for(203) == 424100000


def test_unknown_channel_returns_none():
    cmap = ChannelMap.from_csv(EXAMPLE)
    assert cmap.freq_for(999999) is None


def test_linear_fallback():
    cmap = ChannelMap(base_freq_hz=400_000_000, base_channel=100, step_hz=12500)
    assert cmap.freq_for(100) == 400_000_000
    assert cmap.freq_for(102) == 400_025_000


def test_reverse_lookup():
    cmap = ChannelMap.from_csv(EXAMPLE)
    assert cmap.channel_for(423862500) == 141
    assert cmap.channel_for(423862500 + 5, tol_hz=10) == 141
    assert cmap.channel_for(423862500 + 50, tol_hz=10) is None
