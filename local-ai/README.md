# Local AI kit

Free, private replacements for the paid AI APIs, running on your own server.
Everything speaks the **OpenAI API format**, so most apps (DocuWhisper
included) switch over by changing a base URL and a model name.

| Paid service | Local replacement | Address |
| --- | --- | --- |
| GPT / Claude chat | Ollama (`qwen2.5:14b` / `llama3.1:8b`) | `http://<server>:11434/v1` |
| OpenAI embeddings | Ollama `nomic-embed-text` | `http://<server>:11434/v1` |
| Whisper API | faster-whisper (`whisper_server.py`) | `http://<server>:8000/v1` |

## Install (on the server)

```sh
git clone -b claude/autonomous-ai-voice-chatbot-RoaKI https://github.com/jjsaw911/Nora-.git
cd Nora-/local-ai
./setup.sh
./test.sh localhost some-recording.mp3
```

`setup.sh` checks your GPU and picks model sizes that fit, installs Ollama and
the Whisper server, and runs both as services that start on boot. It's safe to
re-run. Choose a different chat model with `CHAT_MODEL=llama3.1:8b ./setup.sh`.

## Point an app at it

For an app that uses the OpenAI SDK, set:

```sh
OPENAI_BASE_URL=http://10.0.0.234:11434/v1   # chat + embeddings
OPENAI_API_KEY=local                          # anything; not checked
```

and change model names (`gpt-4o` → `qwen2.5:14b`, `text-embedding-3-small` →
`nomic-embed-text`). Transcription calls go to `http://10.0.0.234:8000/v1`
instead — any model name works there. If the app uses one base URL for
everything, it needs a small code change to send audio to port 8000.

Apps built on the Anthropic/Claude SDK need a code change to use the OpenAI
format instead.

**Note:** embeddings from a different model aren't compatible. If DocuWhisper
already stored OpenAI embeddings for your documents, re-index them after
switching.

## Troubleshooting

- `journalctl -u local-whisper -n 50` and `journalctl -u ollama -n 50` show service logs.
- **Out of GPU memory:** chat and Whisper share the GPU. Use a smaller chat
  model (`CHAT_MODEL=llama3.1:8b ./setup.sh`), or a smaller Whisper model by
  editing `whisper.env` and running `sudo systemctl restart local-whisper`.
- **Can't connect from another device:** check the firewall, e.g.
  `sudo ufw allow 11434` and `sudo ufw allow 8000`.
