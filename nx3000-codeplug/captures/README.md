# captures/

Drop raw and decoded capture files here. Large raw captures are gitignored (see
`.gitignore`); keep small, curated decode fixtures under `tests/fixtures/` so they
travel with the tests.

Accepted by `nx3000 capture-parse` / `nx3000.capture.load()`:

- `*.bin`  — raw byte dump (one direction, or undifferentiated).
- `*.csv`  — decoded-byte CSV (sigrok UART export **or** generic COM-sniffer CSV).
             Recognised columns: time/timestamp, dir/direction/channel, data/byte/hex.
- anything else — treated as a timestamped serial-sniff text log
             (`<time> <TX|RX> <hex bytes>` per line; unrecognised lines skipped).

See `docs/capture-log.md` for the journal of what each capture was and what the
radio answered.
