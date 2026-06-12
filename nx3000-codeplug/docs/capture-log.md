# Capture Log

A running journal of every discovery attempt: what was sent (if anything), the
line params used, and exactly what the radio answered. Newest entries on top.
This is the raw record the spec (`docs/protocol.md`) is distilled from.

## How to add an entry

Copy the template below for each session. Keep raw byte dumps short (hex) or
reference a fixture file under `captures/` or `tests/fixtures/`.

```
### YYYY-MM-DD HH:MM — <one-line summary>
- Path: A (KPG-D3 sniff) | B (black-box probe)
- Port / cable: <e.g. /dev/ttyUSB0, CP210x bi-pin>
- Line params: <baud> <framing> (e.g. 9600 8N2)
- TX enabled: yes/no (--allow-tx)
- Sent:    <hex or "(passive listen only)">
- Got:     <hex / fixture ref>
- Result:  <NAK | silence | data | partial>
- Notes / next step:
```

---

## Entries

### (template) — no captures yet

Nothing has been captured from the NX-3320K3 yet. First sessions should:

1. `nx3000 scan --port <PORT>` — passive listen / line-level sanity (no TX).
2. With `--allow-tx`, try Hypothesis H1 handshake at 9600 8N2.
3. If silent/NAK, `nx3000 probe --autobaud` to sweep baud/framing.
4. On any reply, save the bytes and run `nx3000 capture-parse --solve-checksum`.

Record results above this line using the template.
