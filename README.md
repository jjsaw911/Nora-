# Nora — autonomous real-time voice agent

Nora is a voice chatbot built to sound like a person on a call: sub-second
replies, you can interrupt her mid-sentence, and she takes turns the way humans
do. **Phase 1** (this repo) is a browser voice call; the design extends to real
phone calls (VoIP/SIP) in **Phase 2** — see [`ROADMAP.md`](./ROADMAP.md).

## How it works

```
browser mic ──WebRTC──▶ Pipecat transport ──▶ OpenAI Realtime (S2S) ──▶ transport ──▶ browser speaker
                              ▲                          │
                              └──────── tool calls ◀─────┘
```

- **OpenAI Realtime** is a *speech-to-speech* model: audio in, voice out, over a
  WebSocket. It handles voice activity detection, **semantic turn-taking**, and
  **barge-in** natively — that's what makes it feel human, not the word quality.
- **Pipecat** owns the transport (WebRTC now; phone is a swap later) and the
  function-calling loop. We write conversation logic, not packet plumbing.
- The **server sits in the audio path**, so adding a phone in Phase 2 is a
  transport change, not a rewrite.

| File / dir | What it is |
| --- | --- |
| `server/bot.py` | The Pipecat pipeline + OpenAI Realtime wiring (the heart). |
| `server/persona.py` | Nora's personality, voice, and turn-taking config. |
| `server/tools.py` | Function-calling scaffold (ships a real `get_current_time` tool). |
| `client/` | Branded browser UI (no build step; loads Pipecat JS from a CDN). |
| `ROADMAP.md` | Phase 1 detail + the recommended Phase 2 plan. |
| `tunnel.sh`, `ssh/`, `keys/` | SSH tunnel to the remote box (see below). |

## Quick start

Requires Python 3.10+ and an OpenAI API key with Realtime access.

```sh
make install                 # creates .venv and installs deps
cp .env.example .env         # then edit .env: set OPENAI_API_KEY
make run                     # starts Nora on 0.0.0.0:8080 (WebRTC)
```

Then talk to her two ways:

- **Prebuilt UI (verified path):** open `http://localhost:8080/client`.
- **Branded client:** `make client` (serves `client/` on `:3000`) and open
  `http://localhost:3000`, with the server field pointing at the bot.

On the remote box, run `make run` there and reach `:8080` through the SSH tunnel
below; browsers need `localhost` (or HTTPS) for mic access, which the tunnel
gives you.

Configuration (model, voice, host/port) lives in `.env` — see `.env.example`.
Voices: `marin`, `cedar`, `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`,
`shimmer`, `verse`.

## Version notes

The voice stack moves fast. This targets `pipecat-ai >= 0.0.84`, where the
Realtime service lives at `pipecat.services.openai.realtime`. If a newer release
has shifted the API, the canonical reference is Pipecat's
`examples/realtime/realtime-openai.py` and the
[OpenAI Realtime service docs](https://docs.pipecat.ai/server/services/s2s/openai).
`server/bot.py` is small and isolates the moving parts (`build_llm`) for easy pinning.

---

## SSH tunnel to the remote box

Forwards your local **`http://localhost:8080`** to **`localhost:8080`** on the
remote box `154.59.156.22`, so the browser reaches Nora as if she were local
(and gets mic access via `localhost`).

Equivalent to:

```sh
ssh -p 43010 root@154.59.156.22 -L 8080:localhost:8080
```

> Run this from **your own machine** — not from a CI/sandbox, which can't reach
> the remote host.

| Setting | Value |
| --- | --- |
| Host | `154.59.156.22` |
| Port | `43010` |
| User | `root` |
| Local forward | `8080 -> localhost:8080` |

**One-time:** authorize your key on the server:

```sh
ssh-copy-id -i keys/joseph-mac.pub -p 43010 root@154.59.156.22
```

**Connect:**

```sh
./tunnel.sh                 # opens a remote shell with the tunnel active
./tunnel.sh --tunnel-only   # forward only, no shell (good for backgrounding)
```

Override any value with env vars, e.g. `LOCAL_PORT=9090 ./tunnel.sh`. Or use the
`Host nora-tunnel` block in `ssh/config` (`Include` it from `~/.ssh/config`,
then `ssh nora-tunnel`).

**Verify** (with the tunnel open, Nora running on the box):

```sh
curl -v http://localhost:8080/client
```

### Tunnel troubleshooting
- **`bind: Address already in use`** — local `8080` taken: `LOCAL_PORT=9090 ./tunnel.sh`.
- **`Permission denied (publickey)`** — key not authorized yet, or wrong `IdentityFile`.
- **`channel ... open failed: connect failed`** — nothing listening on the
  remote `:8080`; start Nora (`make run`) first.
- **Connection hangs/drops** — keepalive already retries; check host, port
  `43010`, and any firewall.
