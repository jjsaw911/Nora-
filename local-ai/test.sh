#!/usr/bin/env bash
# Smoke-test the local AI services. Run on the server, or from another
# machine:  ./test.sh 10.0.0.234 [some-audio-file]
set -uo pipefail
HOST="${1:-localhost}"
AUDIO="${2:-}"
cd "$(dirname "$0")"
[[ -f whisper.env ]] && source whisper.env
CHAT_MODEL="${CHAT_MODEL:-$(curl -s "http://$HOST:11434/api/tags" | python3 -c 'import json,sys; m=[x["name"] for x in json.load(sys.stdin)["models"] if "embed" not in x["name"]]; print(m[0] if m else "")' 2>/dev/null)}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
ok=0; fail=0
pass() { echo "  PASS  $*"; ok=$((ok+1)); }
bad()  { echo "  FAIL  $*"; fail=$((fail+1)); }

echo "Chat ($CHAT_MODEL)"
reply=$(curl -s "http://$HOST:11434/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$CHAT_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: ready\"}]}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"])' 2>/dev/null)
[[ -n "$reply" ]] && pass "replied: $reply" || bad "no reply from http://$HOST:11434"

echo "Embeddings ($EMBED_MODEL)"
dims=$(curl -s "http://$HOST:11434/v1/embeddings" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$EMBED_MODEL\",\"input\":\"hello\"}" \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["data"][0]["embedding"]))' 2>/dev/null)
[[ -n "$dims" ]] && pass "$dims-dimension vector" || bad "no embedding"

echo "Whisper"
health=$(curl -sf "http://$HOST:8000/health") && pass "$health" || bad "server not reachable on http://$HOST:8000"
if [[ -n "$AUDIO" ]]; then
    text=$(curl -s "http://$HOST:8000/v1/audio/transcriptions" -F "file=@$AUDIO" -F model=whisper-1 -F response_format=text)
    [[ -n "$text" ]] && pass "transcript: $text" || bad "empty transcript"
else
    echo "  (pass an audio file as the 2nd argument to test a real transcription)"
fi

echo; echo "$ok passed, $fail failed"
(( fail == 0 ))
