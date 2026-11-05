#!/usr/bin/env bash
# Launch the local Whisper server. Used by the systemd service; also fine to
# run by hand for debugging:  ./run_whisper.sh
set -euo pipefail
cd "$(dirname "$0")"

# shellcheck disable=SC1091
[[ -f whisper.env ]] && set -a && source whisper.env && set +a

PY=.venv/bin/python

# On GPU, faster-whisper needs cuBLAS/cuDNN; setup.sh installs them as pip
# wheels, so point the loader at them.
if libs=$("$PY" -c 'import os, nvidia.cublas.lib as b, nvidia.cudnn.lib as d; print(os.path.dirname(b.__file__) + ":" + os.path.dirname(d.__file__))' 2>/dev/null); then
    export LD_LIBRARY_PATH="${libs}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PY" -m uvicorn whisper_server:app --host "${WHISPER_HOST:-0.0.0.0}" --port "${WHISPER_PORT:-8000}"
