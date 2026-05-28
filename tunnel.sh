#!/usr/bin/env bash
#
# Open the SSH tunnel to the Nora remote box, forwarding local 8080 -> remote
# localhost:8080. Run this from your own machine (not from a sandbox/CI).
#
#   ./tunnel.sh                 # open a shell on the remote with the tunnel active
#   ./tunnel.sh --tunnel-only   # forward only, no remote shell (backgroundable)
#   ./tunnel.sh -v              # any extra args are passed straight to ssh
#
set -euo pipefail

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_HOST="${REMOTE_HOST:-154.59.156.22}"
REMOTE_PORT="${REMOTE_PORT:-43010}"
LOCAL_PORT="${LOCAL_PORT:-8080}"
FORWARD_HOST="${FORWARD_HOST:-localhost}"
FORWARD_PORT="${FORWARD_PORT:-8080}"

ssh_args=(
    -p "${REMOTE_PORT}"
    -L "${LOCAL_PORT}:${FORWARD_HOST}:${FORWARD_PORT}"
    -o ServerAliveInterval=60
    -o ServerAliveCountMax=3
    -o ExitOnForwardFailure=yes
)

if [[ "${1:-}" == "--tunnel-only" ]]; then
    # -N: do not run a remote command, just hold the forward open.
    ssh_args+=(-N)
    shift
fi

echo "Forwarding http://localhost:${LOCAL_PORT} -> ${REMOTE_HOST}:${FORWARD_PORT} (via ssh ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT})" >&2

exec ssh "${ssh_args[@]}" "$@" "${REMOTE_USER}@${REMOTE_HOST}"
