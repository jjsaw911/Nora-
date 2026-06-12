"""Tests for the capture parsers (CSV / sniff-log / raw bin) and reassembly."""

from nx3000 import capture as cap


def test_parse_byte_field_variants():
    assert cap._parse_byte_field("3F") == b"\x3f"
    assert cap._parse_byte_field("0x3f") == b"\x3f"
    # Bare 2-digit tokens are hex-first (UART-capture convention), so "63" is 0x63.
    assert cap._parse_byte_field("63") == b"\x63"
    # Decimal fallback only kicks in for tokens that aren't a clean hex byte.
    assert cap._parse_byte_field("255") == b"\xff"
    assert cap._parse_byte_field("52 4F 4D") == b"ROM"
    assert cap._parse_byte_field("'R'") == b"R"


def test_parse_csv_with_header_and_direction():
    text = (
        "time,direction,data\n"
        "0.001,tx,0x50\n"
        "0.002,tx,52\n"
        "0.010,rx,0x06\n"
    )
    capture = cap.parse_csv(text)
    reasm = cap.reassemble(capture)
    assert reasm.tx == b"PR"
    assert reasm.rx == b"\x06"


def test_parse_csv_headerless_falls_back_to_last_column():
    text = "0.001,0x41\n0.002,0x42\n"
    capture = cap.parse_csv(text)
    assert capture.stream() == b"AB"


def test_parse_csv_skips_undecodable_rows():
    text = "time,data\n0.001,0x41\n0.002,annotation-noise\n0.003,0x42\n"
    capture = cap.parse_csv(text)
    assert capture.stream() == b"AB"


def test_parse_sniff_log():
    log = (
        "# session start\n"
        "0.012345  TX  50 52 4F 47\n"
        "[12.5ms] RX: 16\n"
        "garbage line that should be skipped\n"
        "0.030 RX 06\n"
    )
    capture = cap.parse_sniff_log(log)
    reasm = cap.reassemble(capture)
    assert reasm.tx == b"PROG"
    assert reasm.rx == b"\x16\x06"


def test_raw_bin_roundtrip(tmp_path):
    f = tmp_path / "dump.bin"
    f.write_bytes(b"\x00\x01\x02\x03")
    capture = cap.parse_raw_bin(f)
    assert capture.stream() == b"\x00\x01\x02\x03"


def test_load_dispatches_by_extension(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("data\n0x41\n0x42\n")
    assert cap.load(f).stream() == b"AB"


def test_hexdump_format():
    out = cap.hexdump(b"AB")
    assert "41 42" in out
    assert "AB" in out
