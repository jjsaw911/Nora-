# Nora — roadmap

## The north-star metric

Everything here optimizes one number: **time-to-first-audio after the caller
stops speaking**, plus clean **barge-in**. Humans expect a reply gap of
~200–500 ms. Below ~800 ms and with natural prosody + interruptions, callers
stop being able to tell it's a machine. The architecture is built around that,
not around the model's word quality (which is already past the bar).

---

## Phase 1 — Real-time browser voice (this repo) ✅ scaffolded

**Goal:** a stranger on a web call can't tell Nora is a machine.

| Concern | Choice | Why |
| --- | --- | --- |
| Voice engine | **OpenAI Realtime (speech-to-speech)** over WebSocket | Native VAD, semantic turn-taking, barge-in, emotion/laughs. Lowest-latency path to "human". |
| Transport | **WebRTC** (Pipecat `SmallWebRTC`) | Browser-grade echo cancellation, jitter buffering, packet-loss recovery. |
| Orchestration | **Pipecat** (Python) | Owns transport, interruption handling, and the function-calling loop so we write conversation logic, not packet plumbing. |
| Turn-taking | **Semantic turn detection** | Waits until you've *finished a thought*, not just paused — the biggest "feels human" lever. |
| Tools | Function-calling scaffold (`get_current_time`) | Proves the autonomous action path end-to-end; easy to extend. |
| Hosting | The remote box, exposed on `:8080` via the existing SSH tunnel | Server sits in the audio path, so the phone path in Phase 2 is a transport swap, not a rewrite. |

**Done when:** sub-second responses, you can interrupt Nora mid-sentence, and a
tool call ("what time is it in Tokyo?") works on a live call.

---

## Phase 2 — recommended next (in priority order)

The build is deliberately structured so each of these is additive.

### 2.1 Telephony — make/receive real phone calls (highest leverage)
You already flagged VoIP/SIP. Because the server is in the audio path, this is a
**transport swap**, not a rewrite:
- **Easiest:** Twilio / Telnyx **Media Streams** → audio over WebSocket to the
  same bot. Pipecat has first-class `twilio`/`telnyx` transports (already stubbed
  in `transport_params`). Get a number, point its webhook at the box, run
  `-t twilio`.
- **Most control / true SIP:** a SIP trunk (Telnyx/Twilio Elastic SIP, or
  self-hosted **Asterisk/FreeSWITCH**) ↔ LiveKit SIP or Pipecat. Needed for
  carrier-grade routing, your own DIDs, and on-prem.
- **Watch-outs:** phone audio is 8 kHz μ-law (narrowband) — quality drops vs
  WebRTC; tune the voice for it. PSTN adds ~100–300 ms each way, so the latency
  budget tightens. DTMF, call transfer, and voicemail detection become real
  features.

### 2.2 Memory & knowledge
- **Short-term:** persist transcripts + a rolling summary per caller.
- **Long-term:** vector store (pgvector / Qdrant) for caller history and a
  RAG tool so Nora answers from *your* documents, not just the base model.

### 2.3 Autonomy & tools
- Real tools: calendar booking, CRM lookups/writes, web search, send SMS/email.
- **Outbound** campaigns: Nora *initiates* calls (reminders, follow-ups) with
  guardrails, scheduling, and consent/compliance handling.
- A tool-permission + confirmation layer for anything irreversible.

### 2.4 Naturalness polish
- Backchanneling ("mhm", "right") and filler while tools run, to kill dead air.
- Voice cloning / a custom branded voice (ElevenLabs/Cartesia) if you move parts
  to a cascaded pipeline for cost or a specific voice.
- Multilingual + accent matching.

### 2.5 Production hardening
- Multi-session concurrency + a session/worker manager; load test for the box.
- Auth on the signaling endpoint; rate limiting; TLS (real domain, not just the
  tunnel).
- Observability: per-turn latency metrics, call recordings (with consent),
  transcripts dashboard, cost-per-minute tracking.
- **Cost/privacy fork:** evaluate a self-hosted cascaded stack (Whisper/Moonshine
  STT + open LLM + Kokoro/XTTS) on a GPU to drop per-minute API spend and keep
  audio on-prem. Keep the realtime API for quality-critical calls.
- Safety: abuse/jailbreak handling, PII redaction in logs, call-recording disclosure.

---

## Suggested sequence
1. Land Phase 1, validate latency + barge-in on real hardware/network.
2. **2.1 Twilio Media Streams** — get Nora on a phone number (biggest "wow").
3. **2.2 memory** + **2.3 one real tool** (calendar) — make her useful.
4. **2.5 hardening** before anyone but you calls her.
5. Revisit cascaded/self-hosted only once volume makes API cost matter.
