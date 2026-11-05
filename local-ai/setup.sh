#!/usr/bin/env bash
# One-shot installer: turns this Linux box into a free, local replacement for
# the paid AI APIs (chat, embeddings, speech-to-text), all OpenAI-compatible.
#
#   Ollama          -> chat + embeddings   http://<server>:11434/v1
#   local Whisper   -> transcription       http://<server>:8000/v1
#
# Run it from this folder as your normal user (it uses sudo where needed):
#   ./setup.sh
# Safe to re-run; it skips what's already done.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- hardware
say "Checking hardware"
VRAM_MB=0
if command -v nvidia-smi >/dev/null 2>&1; then
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')
    echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1) (${VRAM_MB} MB)"
else
    echo "No NVIDIA GPU found - everything will run on the CPU (slower)."
fi
echo "RAM: $(free -g | awk '/Mem:/ {print $2}') GB, CPU cores: $(nproc)"

# Pick sizes that fit. Override with CHAT_MODEL=... ./setup.sh
if   (( VRAM_MB >= 20000 )); then DEF_CHAT=qwen2.5:14b; WMODEL=large-v3-turbo; WDEV=cuda; WCOMP=float16
elif (( VRAM_MB >= 10000 )); then DEF_CHAT=qwen2.5:14b; WMODEL=large-v3-turbo; WDEV=cuda; WCOMP=int8_float16
elif (( VRAM_MB >= 6000 ));  then DEF_CHAT=llama3.1:8b; WMODEL=small;          WDEV=cuda; WCOMP=int8_float16
else                              DEF_CHAT=llama3.2:3b; WMODEL=small;          WDEV=cpu;  WCOMP=int8
fi
CHAT_MODEL="${CHAT_MODEL:-$DEF_CHAT}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
echo "Chat model: $CHAT_MODEL | Embeddings: $EMBED_MODEL | Whisper: $WMODEL on $WDEV"

# ------------------------------------------------------------------ Ollama
say "Installing Ollama"
if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "already installed: $(ollama --version 2>/dev/null | head -1)"
fi

# By default Ollama only listens on localhost; open it to the LAN/Tailscale.
say "Letting other devices reach Ollama"
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'CONF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
CONF
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl restart ollama
for _ in $(seq 1 30); do curl -sf localhost:11434/api/tags >/dev/null && break; sleep 1; done

say "Downloading models (first time can take a while)"
ollama pull "$CHAT_MODEL"
ollama pull "$EMBED_MODEL"

# ----------------------------------------------------------------- Whisper
say "Setting up local Whisper"
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' 2>/dev/null; then
    sudo apt-get update && sudo apt-get install -y python3-venv
fi
command -v ffmpeg >/dev/null 2>&1 || sudo apt-get install -y ffmpeg
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
if [[ "$WDEV" == cuda ]]; then
    .venv/bin/pip install -q nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
fi

cat > whisper.env <<ENV
WHISPER_MODEL=$WMODEL
WHISPER_DEVICE=$WDEV
WHISPER_COMPUTE=$WCOMP
WHISPER_HOST=0.0.0.0
WHISPER_PORT=8000
ENV
chmod +x run_whisper.sh

sudo tee /etc/systemd/system/local-whisper.service >/dev/null <<UNIT
[Unit]
Description=Local OpenAI-compatible Whisper server
After=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$HERE
ExecStart=$HERE/run_whisper.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now local-whisper
sudo systemctl restart local-whisper

say "Waiting for Whisper to load its model"
for _ in $(seq 1 120); do curl -sf localhost:8000/health >/dev/null && break; sleep 2; done
curl -sf localhost:8000/health || { echo "Whisper didn't start - see: journalctl -u local-whisper -n 50"; exit 1; }

# ------------------------------------------------------------------ summary
IP=$(hostname -I | awk '{print $1}')
say "Done. Point your apps at:"
cat <<SUM
  Chat / summaries : http://$IP:11434/v1   model "$CHAT_MODEL"
  Embeddings       : http://$IP:11434/v1   model "$EMBED_MODEL"
  Transcription    : http://$IP:8000/v1    (any model name, e.g. "whisper-1")
  API key          : anything (e.g. "local") - nothing checks it

Check it all with:  ./test.sh
SUM
