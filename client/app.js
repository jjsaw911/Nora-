// Branded browser client for Nora.
//
// Thin wrapper over the Pipecat JS client + SmallWebRTC transport. It POSTs a
// WebRTC offer to the bot server's signaling endpoint (`/api/offer`, served by
// the Pipecat dev runner) and pipes Nora's audio into the <audio> element.
//
// Loaded straight from a CDN so there's no build step — open index.html via any
// static server, or let the bot server host this folder.

import { PipecatClient } from "https://esm.sh/@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "https://esm.sh/@pipecat-ai/small-webrtc-transport";

const $ = (id) => document.getElementById(id);
const orb = $("orb");
const statusEl = $("status");
const toggle = $("toggle");
const transcript = $("transcript");
const serverInput = $("server");
const botAudio = $("bot-audio");

// Default the server field to wherever this page is served from.
serverInput.value = `${location.protocol}//${location.host}`;

let client = null;
let live = false;

function setState(state, text) {
  orb.dataset.state = state;
  if (text) statusEl.textContent = text;
}

function addLine(role, text) {
  if (!text) return;
  const el = document.createElement("div");
  el.className = `line ${role}`;
  el.innerHTML = `<b>${role === "user" ? "You" : "Nora"}</b>${text}`;
  transcript.append(el);
  transcript.scrollTop = transcript.scrollHeight;
}

async function start() {
  const base = serverInput.value.replace(/\/$/, "");

  client = new PipecatClient({
    transport: new SmallWebRTCTransport(),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onConnected: () => setState("listening", "Connected — say hi"),
      onDisconnected: () => stop(),
      onBotStartedSpeaking: () => setState("speaking", "Nora is speaking…"),
      onBotStoppedSpeaking: () => setState("listening", "Listening…"),
      onUserTranscript: (d) => d?.final && addLine("user", d.text),
      onBotTranscript: (d) => addLine("bot", d?.text),
      // Route Nora's audio track to the page.
      onTrackStarted: (track, participant) => {
        if (participant?.local || track.kind !== "audio") return;
        botAudio.srcObject = new MediaStream([track]);
      },
      onError: (e) => setState("idle", `Error: ${e?.message ?? e}`),
    },
  });

  setState("connecting", "Connecting…");
  toggle.textContent = "End call";
  toggle.classList.add("is-live");
  live = true;

  try {
    await client.connect({ connection_url: `${base}/api/offer` });
  } catch (err) {
    setState("idle", `Couldn't connect: ${err?.message ?? err}`);
    await stop();
  }
}

async function stop() {
  live = false;
  toggle.textContent = "Start call";
  toggle.classList.remove("is-live");
  setState("idle", "Call ended");
  try {
    await client?.disconnect();
  } catch { /* already gone */ }
  client = null;
  if (botAudio.srcObject) botAudio.srcObject = null;
}

toggle.addEventListener("click", () => (live ? stop() : start()));
