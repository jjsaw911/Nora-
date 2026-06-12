"""nx3000 command-line interface.

Subcommands (per CLAUDE.md):

* ``scan``          — passive line/baud listen (NO TX, always safe).
* ``probe``         — active handshake sweep (requires --allow-tx; allowlisted).
* ``capture-parse`` — decode a logic/sniffer capture into a framed byte stream.
* ``read``          — Phase 2 block-walk codeplug read (requires --allow-tx).
* ``verify``        — Phase 3: read twice, assert byte-identical.

The **read-only-by-default** rule is enforced here too: any subcommand that can
transmit refuses to do so unless ``--allow-tx`` is passed, and even then only
allowlisted (read/handshake) opcodes reach the wire.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def _add_serial_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--port", required=True, help="serial port (e.g. /dev/ttyUSB0 or COM3)")
    p.add_argument("--baud", type=int, default=9600, help="baud rate (default 9600, H1)")
    p.add_argument("--bytesize", type=int, default=8, choices=(5, 6, 7, 8))
    p.add_argument("--parity", default="N", choices=("N", "E", "O", "M", "S"))
    p.add_argument("--stopbits", type=float, default=2, choices=(1, 1.5, 2))
    p.add_argument("--timeout", type=float, default=1.0)
    p.add_argument(
        "--allow-tx",
        action="store_true",
        help="MASTER SAFETY GATE: permit transmitting (off by default). Even when "
        "set, only allowlisted read/handshake opcodes can be sent.",
    )


def _line_params(args):
    from .serialio import LineParams

    return LineParams(
        baudrate=args.baud,
        bytesize=args.bytesize,
        parity=args.parity,
        stopbits=args.stopbits,
        timeout=args.timeout,
    )


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_scan(args) -> int:
    from . import autobaud

    print("Passive scan (no TX). Listening at candidate line params...\n")
    results = autobaud.passive_scan(args.port, timeout=args.timeout)
    for r in results[:12]:
        flag = "" if r.score > 0 else "  (no/!plausible data)"
        print(f"  {str(r.params):<16} score={r.score:5.2f}{flag}  {r.note}")
        if r.sample:
            print(f"      sample: {r.sample[:32].hex(' ')}")
    print("\nFeed any promising sample to `capture-parse` / the checksum solver.")
    return 0


def cmd_probe(args) -> int:
    if not args.allow_tx:
        print(
            "probe transmits the enter-program handshake, which is gated behind "
            "--allow-tx (read-only by default). Re-run with --allow-tx to proceed.\n"
            "Only the allowlisted handshake/read opcodes can ever be sent.",
            file=sys.stderr,
        )
        return 2
    from . import autobaud

    print("Active handshake sweep (--allow-tx set). Sending allowlisted PROGRAM only...\n")
    results = autobaud.active_handshake_probe(args.port, timeout=args.timeout)
    for r in results[:12]:
        mark = "  <== ACK" if r.handshake_ack else ""
        print(f"  {str(r.params):<16} score={r.score:5.2f}  {r.note}{mark}")
        if r.sample:
            print(f"      reply: {r.sample.hex(' ')}")
    return 0


def cmd_capture_parse(args) -> int:
    from . import capture as cap
    from . import checksum as cs

    capture = cap.load(args.file)
    reasm = cap.reassemble(capture)
    print(f"Loaded {len(capture)} bytes from {capture.source} ({len(capture.events)} events)\n")
    print(f"  host->radio (tx): {len(reasm.tx)} bytes")
    print(f"  radio->host (rx): {len(reasm.rx)} bytes")
    print(f"  combined:         {len(reasm.combined)} bytes\n")

    show = reasm.rx if reasm.rx else reasm.combined
    if show:
        print("First bytes (rx if separable, else combined):")
        print(cap.hexdump(show[: args.bytes]))

    if args.solve_checksum:
        if not (args.block and args.expected is not None):
            print(
                "\n--solve-checksum needs --block <hexfile|hex> and --expected <byte> "
                "(the captured block and its trailing checksum).",
                file=sys.stderr,
            )
            return 2
        block = _load_bytes_arg(args.block)
        hits = cs.solve(block, args.expected)
        print(f"\nChecksum solver over {len(block)} bytes, expected 0x{args.expected:02x}:")
        if hits:
            for h in hits:
                print(f"  MATCH: {h.algorithm} (width {h.width_bits})")
            print("  -> confirm with more samples via checksum.solve_many()")
        else:
            print("  no candidate matched; widen the catalogue (install crccheck) "
                  "or check block boundaries.")
    return 0


def cmd_read(args) -> int:
    if not args.allow_tx:
        print(
            "read must transmit read commands; gated behind --allow-tx (read-only by "
            "default). Re-run with --allow-tx. No write/erase opcode is ever sent.",
            file=sys.stderr,
        )
        return 2
    from .reader import ReadConfig, read_codeplug, save
    from .serialio import SerialLink

    print(
        "WARNING: the NX-3000 read protocol is UNCONFIRMED. This will transmit the "
        "hypothesised (allowlisted) read handshake/commands only. Verify the result "
        "with `verify` before trusting it.\n"
    )
    link = SerialLink(port=args.port, params=_line_params(args), allow_tx=True)
    config = ReadConfig(
        start_block=args.start,
        end_block=args.end,
        checksum_algorithm=args.checksum,
    )
    with link:
        result = read_codeplug(link, config)
    bin_path, manifest_path = save(result, out_dir=args.out, serial=args.serial)
    print(f"Wrote {len(result.data)} bytes -> {bin_path}")
    print(f"Manifest          -> {manifest_path}")
    print(f"sha256            -> {result.sha256}")
    return 0


def cmd_verify(args) -> int:
    if not args.allow_tx:
        print("verify performs two reads and needs --allow-tx (read-only by default).",
              file=sys.stderr)
        return 2
    from .reader import ReadConfig, read_codeplug, verify_two_reads
    from .serialio import SerialLink

    config = ReadConfig(start_block=args.start, end_block=args.end, checksum_algorithm=args.checksum)
    reads = []
    for n in (1, 2):
        print(f"Read pass {n}/2...")
        link = SerialLink(port=args.port, params=_line_params(args), allow_tx=True)
        with link:
            reads.append(read_codeplug(link, config))
    ok = verify_two_reads(*reads)
    print(f"\nPass 1 sha256: {reads[0].sha256}")
    print(f"Pass 2 sha256: {reads[1].sha256}")
    print("RESULT:", "IDENTICAL ✓ (verified, reproducible)" if ok else "MISMATCH ✗ — not trustworthy")
    return 0 if ok else 1


def _load_bytes_arg(value: str) -> bytes:
    """Accept either a path to a binary file or an inline hex string."""
    from pathlib import Path

    p = Path(value)
    if p.exists():
        return p.read_bytes()
    return bytes.fromhex(value.replace("0x", "").replace(",", " "))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nx3000",
        description="Read-only codeplug backup tool for the Kenwood NX-3000 series. "
        "Read-only by default; TX requires --allow-tx and is opcode-allowlisted.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="passive line/baud listen (no TX)")
    _add_serial_opts(p_scan)
    p_scan.set_defaults(func=cmd_scan)

    p_probe = sub.add_parser("probe", help="active handshake sweep (requires --allow-tx)")
    _add_serial_opts(p_probe)
    p_probe.set_defaults(func=cmd_probe)

    p_cap = sub.add_parser("capture-parse", help="decode a logic/sniffer capture")
    p_cap.add_argument("file", help="capture file (.bin / .csv / sniff log)")
    p_cap.add_argument("--bytes", type=int, default=256, help="how many bytes to hexdump")
    p_cap.add_argument("--solve-checksum", action="store_true", help="run the checksum solver")
    p_cap.add_argument("--block", help="block bytes (path or hex) for --solve-checksum")
    p_cap.add_argument("--expected", type=lambda x: int(x, 0), help="expected checksum byte/word")
    p_cap.set_defaults(func=cmd_capture_parse)

    p_read = sub.add_parser("read", help="Phase 2 block-walk read (requires --allow-tx)")
    _add_serial_opts(p_read)
    p_read.add_argument("--start", type=lambda x: int(x, 0), default=0x00, help="start block")
    p_read.add_argument("--end", type=lambda x: int(x, 0), default=0xBF, help="end block (inclusive)")
    p_read.add_argument("--checksum", default=None, help="checksum algorithm to validate (e.g. sum8)")
    p_read.add_argument("--out", default=".", help="output directory")
    p_read.add_argument("--serial", default=None, help="radio serial for the filename/manifest")
    p_read.set_defaults(func=cmd_read)

    p_ver = sub.add_parser("verify", help="Phase 3: read twice, assert byte-identical")
    _add_serial_opts(p_ver)
    p_ver.add_argument("--start", type=lambda x: int(x, 0), default=0x00)
    p_ver.add_argument("--end", type=lambda x: int(x, 0), default=0xBF)
    p_ver.add_argument("--checksum", default=None)
    p_ver.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
