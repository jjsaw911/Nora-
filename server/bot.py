"""Nora — Phase 1 real-time voice agent.

Architecture (server-in-the-audio-path, so it generalizes to phone/SIP later):

    browser mic ──WebRTC──▶ Pipecat transport ──▶ OpenAI Realtime (S2S) ──▶ transport ──▶ browser speaker
                                  ▲                         │
                                  └──── tool calls ◀────────┘

The OpenAI Realtime (speech-to-speech) model handles VAD, semantic turn
detection, barge-in/interruptions and natural prosody natively — that's what
gets us human-like, sub-second turn-taking. Pipecat owns the transport
(WebRTC today; Twilio/Telnyx/Daily-PSTN are a one-line swap in Phase 2) and the
function-calling loop.

Run it (on the box, behind your :8080 tunnel):

    python server/bot.py -t webrtc --host 0.0.0.0 --port 8080

then open the prebuilt client at  http://localhost:8080/client  (through the
tunnel) — or use the branded client in ../client.
"""

import os
import sys

from dotenv import load_dotenv
from loguru import logger

from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    AudioOutput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    SemanticTurnDetection,
    SessionProperties,
)
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

# Allow `python server/bot.py` (cwd-relative) and `python -m server.bot`.
try:
    from server.persona import GREETING_PROMPT, REALTIME_MODEL, SYSTEM_INSTRUCTION, VOICE
    from server.tools import build_tools_schema, register_tools
except ImportError:  # running with server/ itself on sys.path
    from persona import GREETING_PROMPT, REALTIME_MODEL, SYSTEM_INSTRUCTION, VOICE
    from tools import build_tools_schema, register_tools

load_dotenv(override=True)


# One config per supported transport. WebRTC (browser) is Phase 1; the telephony
# entries are here so the phone path in Phase 2 is a `-t twilio` flip, not a rewrite.
transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    "daily": lambda: DailyParams(audio_in_enabled=True, audio_out_enabled=True),
    "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
}


def build_llm() -> OpenAIRealtimeLLMService:
    """Construct the OpenAI Realtime S2S service with Nora's voice + turn-taking."""
    session_properties = SessionProperties(
        audio=AudioConfiguration(
            input=AudioInput(
                # Transcription is for logging/observability; the S2S model hears raw audio.
                transcription=InputAudioTranscription(),
                # Semantic turn detection = waits until you've *finished a thought*,
                # not just paused. This is the single biggest "feels human" setting.
                turn_detection=SemanticTurnDetection(),
                noise_reduction=InputAudioNoiseReduction(type="near_field"),
            ),
            output=AudioOutput(voice=VOICE),
        ),
    )
    return OpenAIRealtimeLLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAIRealtimeLLMService.Settings(
            model=REALTIME_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            session_properties=session_properties,
        ),
    )


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    logger.info("Nora: starting session")

    llm = build_llm()
    register_tools(llm)

    # Seed the conversation with a developer-role nudge so the greeting sounds
    # spontaneous, and advertise our tools to the model.
    context = OpenAILLMContext(
        messages=[{"role": "developer", "content": GREETING_PROMPT}],
        tools=build_tools_schema(),
    )
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,  # barge-in: caller can cut Nora off mid-sentence
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Nora: caller connected — greeting")
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Nora: caller disconnected — ending session")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments) -> None:
    """Entry point the Pipecat dev runner calls for each new connection."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.")
    from pipecat.runner.run import main

    main()
