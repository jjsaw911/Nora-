"""Command-line entry point for the Nora NXDN decoder.

Subcommands:

    decode   Demodulate an IQ file (or live rtl_sdr) and print NXDN frames.
    trunk    Two-dongle trunk follower: park on a control channel, follow grants.
    info     Print the build/protocol constants in use.

Run ``python -m nora_nxdn --help`` for details.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

import numpy as np

from . import __version__
from .channelmap import ChannelMap
from .dsp import Demodulator
from .framing import find_sync, iter_sync
from .lich import LICH_DIBITS, decode_lich
from .scramble import pn95_descramble_dibits
from .sdr import IqFileSource, RtlSdrIqSource


def _decode_blocks(demod: Demodulator, source, *, max_errors: int) -> int:
    """Demodulate every block, print detected NXDN frames. Returns frame count."""
    frames = 0
    for block in source.blocks():
        symbols = demod.soft_symbols(block)
        if symbols.size < 32:
            continue
        for m in iter_sync(symbols, max_errors=max_errors):
            # LICH dibits sit right after the 18-symbol sync.
            start = m.position + 18
            window = symbols[start : start + LICH_DIBITS]
            if len(window) < LICH_DIBITS:
                continue
            # Slice the LICH symbols to dibits, then PN95-descramble.
            from .dsp import slice_symbols

            raw = slice_symbols(window)
            descr = pn95_descramble_dibits(raw)
            lich = decode_lich(descr)
            frames += 1
            polarity = "inv" if m.inverted else "norm"
            flag = "ok" if lich.parity_ok else "BAD"
            print(
                f"sync={m.sync_type.value:<8} pol={polarity} "
                f"lich=0x{lich.code:02X} parity={flag} "
                f"off={lich.off_bits}/8 :: {lich.description}"
            )
    return frames


def cmd_decode(args: argparse.Namespace) -> int:
    demod = Demodulator(
        sample_rate=args.sample_rate, symbol_rate=args.symbol_rate
    )
    if args.iq_file:
        source = IqFileSource(args.iq_file, sample_rate=args.sample_rate)
    else:
        source = RtlSdrIqSource(
            freq_hz=args.freq,
            sample_rate=args.sample_rate,
            device_index=args.device,
            serial=args.serial,
            gain=args.gain,
            ppm=args.ppm,
        )
    try:
        n = _decode_blocks(demod, source, max_errors=args.max_errors)
    finally:
        source.close()
    print(f"\n{n} NXDN frame(s) decoded.", file=sys.stderr)
    return 0 if n else 1


def cmd_trunk(args: argparse.Namespace) -> int:
    # Wiring the full live trunk loop needs hardware; here we validate the
    # configuration and report what would run. The control logic itself lives
    # in nora_nxdn.trunk and is exercised by the test suite.
    cmap = ChannelMap.from_csv(args.channel_map)
    print(f"Loaded {len(cmap)} channels from {args.channel_map}")
    print(f"Control dongle : device {args.control_device} @ {args.control_freq} Hz")
    print(f"Voice dongle   : device {args.voice_device} (follows grants)")
    print(f"Hangtime       : {args.hangtime}s")
    print(
        "Live trunking requires two RTL-SDR dongles; see docs/architecture.md "
        "for the runtime wiring."
    )
    return 0


def cmd_info(_args: argparse.Namespace) -> int:
    from .framing import _PATTERNS

    print(f"nora-nxdn {__version__}")
    print("Frame sync words (sign patterns, '1'=+, '3'=-):")
    for t, p in _PATTERNS.items():
        print(f"  {t.value:<10} {p}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nora-nxdn", description="NXDN protocol decoder for RTL-SDR (macOS)."
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("decode", help="decode an IQ file or live rtl_sdr")
    d.add_argument("--iq-file", help="replay a cu8 IQ capture instead of live SDR")
    d.add_argument("--freq", type=int, default=0, help="tune frequency (Hz)")
    d.add_argument("--sample-rate", type=float, default=240000.0)
    d.add_argument(
        "--symbol-rate", type=float, default=4800.0, help="2400 or 4800 baud"
    )
    d.add_argument("--device", type=int, default=0, help="rtl_sdr device index")
    d.add_argument("--serial", help="rtl_sdr device serial (overrides --device)")
    d.add_argument("--gain", type=float, default=None)
    d.add_argument("--ppm", type=int, default=0)
    d.add_argument("--max-errors", type=int, default=1, help="sync fuzz tolerance")
    d.set_defaults(func=cmd_decode)

    t = sub.add_parser("trunk", help="dual-dongle trunk follower")
    t.add_argument("--channel-map", required=True, help="channel(dec),freq(Hz) CSV")
    t.add_argument("--control-freq", type=int, required=True)
    t.add_argument("--control-device", type=int, default=0)
    t.add_argument("--voice-device", type=int, default=1)
    t.add_argument("--hangtime", type=float, default=3.0)
    t.set_defaults(func=cmd_trunk)

    i = sub.add_parser("info", help="print protocol constants")
    i.set_defaults(func=cmd_info)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
