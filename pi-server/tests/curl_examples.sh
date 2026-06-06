#!/usr/bin/env bash
# M2 verification — drive the control API with curl. Run while the server is up;
# with a real dongle you should HEAR the tuned station change.
set -euo pipefail
BASE="${BASE:-http://localhost:8080}"

echo "== /status ==";  curl -s "$BASE/status";  echo
echo "== /config ==";  curl -s "$BASE/config";  echo

echo "== tune to 96.9 MHz =="
curl -s -X POST "$BASE/tune"    -H 'content-type: application/json' -d '{"freq_hz": 96900000}'; echo
echo "== gain 28 dB =="
curl -s -X POST "$BASE/gain"    -H 'content-type: application/json' -d '{"gain_db": 28.0}'; echo
echo "== gain auto =="
curl -s -X POST "$BASE/gain"    -H 'content-type: application/json' -d '{"gain_db": "auto"}'; echo
echo "== mode wbfm =="
curl -s -X POST "$BASE/mode"    -H 'content-type: application/json' -d '{"mode": "wbfm"}'; echo
echo "== squelch -40 dB =="
curl -s -X POST "$BASE/squelch" -H 'content-type: application/json' -d '{"db": -40}'; echo

echo "== /status (after) ==";  curl -s "$BASE/status";  echo
