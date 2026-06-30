"""Tool (function-calling) scaffold for Nora.

Phase 1 ships one real, dependency-free tool (current time) so the end-to-end
function-calling path is exercised and demonstrable. Add new tools by writing a
handler + a FunctionSchema and registering both in `register_tools` /
`build_tools_schema`. Phase 2 expands this into calendar, CRM, RAG/memory, etc.
"""

import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams


async def get_current_time(params: FunctionCallParams) -> None:
    """Return the current local time for an optional IANA timezone."""
    tz_name = (params.arguments or {}).get("timezone") or "UTC"
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(f"Unknown timezone '{tz_name}', falling back to UTC")
        tz_name = "UTC"
        now = datetime.now(ZoneInfo("UTC"))

    await params.result_callback(
        {
            "timezone": tz_name,
            "iso": now.isoformat(timespec="minutes"),
            "spoken": now.strftime("%-I:%M %p on %A, %B %-d"),
        }
    )


_current_time_schema = FunctionSchema(
    name="get_current_time",
    description="Get the current date and time, optionally for a specific timezone.",
    properties={
        "timezone": {
            "type": "string",
            "description": "IANA timezone name, e.g. 'America/New_York'. Defaults to UTC.",
        },
    },
    required=[],
)


async def send_text_message(params: FunctionCallParams) -> None:
    """Send the user a text message via Twilio (SMS or WhatsApp).

    One code path covers both channels — Twilio's Messages API only differs by a
    `whatsapp:` address prefix. The channel and the to/from numbers come from the
    environment so Nora never hardcodes a recipient. See .env.example.

    The Twilio SDK is synchronous; we run it in a worker thread so a slow network
    call can't stall the realtime audio pipeline.
    """
    body = ((params.arguments or {}).get("message") or "").strip()
    if not body:
        await params.result_callback({"status": "error", "reason": "empty message"})
        return

    channel = os.environ.get("NORA_TEXT_CHANNEL", "sms").strip().lower()
    to_number = os.environ.get("NORA_TEXT_TO")
    from_number = os.environ.get("NORA_TEXT_FROM")
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    if not all([to_number, from_number, account_sid, auth_token]):
        logger.warning("send_text_message called but Twilio env vars are not fully set")
        await params.result_callback(
            {"status": "error", "reason": "texting is not configured on the server"}
        )
        return

    if channel == "whatsapp":
        to_addr, from_addr = f"whatsapp:{to_number}", f"whatsapp:{from_number}"
    else:
        to_addr, from_addr = to_number, from_number

    def _send() -> str:
        # Imported lazily so the module still loads if twilio isn't installed.
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        return client.messages.create(body=body, from_=from_addr, to=to_addr).sid

    try:
        message_sid = await asyncio.to_thread(_send)
        logger.info(f"Sent {channel} message {message_sid}")
        await params.result_callback({"status": "sent", "channel": channel, "sid": message_sid})
    except Exception as exc:  # network / auth / unverified-number etc.
        logger.error(f"send_text_message failed: {exc}")
        await params.result_callback({"status": "error", "reason": str(exc)})


_send_text_schema = FunctionSchema(
    name="send_text_message",
    description=(
        "Send the user a text message (SMS or WhatsApp) on their phone. Use when "
        "something is worth having in writing — a reminder, a link, a phone number, "
        "or a short summary of what was discussed."
    ),
    properties={
        "message": {
            "type": "string",
            "description": "The message body to send. Keep it concise and self-contained.",
        },
    },
    required=["message"],
)


def build_tools_schema() -> ToolsSchema:
    """The full set of tools advertised to the model."""
    return ToolsSchema(standard_tools=[_current_time_schema, _send_text_schema])


def register_tools(llm) -> None:
    """Wire tool names to their async handlers on the LLM service."""
    llm.register_function("get_current_time", get_current_time)
    llm.register_function("send_text_message", send_text_message)
