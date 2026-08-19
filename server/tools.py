"""Tool (function-calling) scaffold for Nora.

Phase 1 ships one real, dependency-free tool (current time) so the end-to-end
function-calling path is exercised and demonstrable. Add new tools by writing a
handler + a FunctionSchema and registering both in `register_tools` /
`build_tools_schema`. Phase 2 expands this into calendar, CRM, RAG/memory, etc.
"""

import asyncio
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

try:
    from server.imagegen import generate_selfie_png
except ImportError:  # running with server/ itself on sys.path
    from imagegen import generate_selfie_png


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


def _twilio_addresses() -> tuple[str, str, str, str] | None:
    """Resolve (to_addr, from_addr, sid, token) from the environment.

    Applies the `whatsapp:` prefix when NORA_TEXT_CHANNEL=whatsapp. Returns None
    if the Twilio configuration is incomplete.
    """
    channel = os.environ.get("NORA_TEXT_CHANNEL", "sms").strip().lower()
    to_number = os.environ.get("NORA_TEXT_TO")
    from_number = os.environ.get("NORA_TEXT_FROM")
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

    if not all([to_number, from_number, account_sid, auth_token]):
        return None

    if channel == "whatsapp":
        return f"whatsapp:{to_number}", f"whatsapp:{from_number}", account_sid, auth_token
    return to_number, from_number, account_sid, auth_token


async def _twilio_send(body: str | None, media_urls: list[str] | None = None) -> str:
    """Send one Twilio message (optionally with media) and return its SID.

    The Twilio SDK is synchronous, so the network call runs in a worker thread —
    a slow send can't stall the realtime audio pipeline. Raises on failure.
    """
    resolved = _twilio_addresses()
    if resolved is None:
        raise RuntimeError("texting is not configured on the server")
    to_addr, from_addr, account_sid, auth_token = resolved

    def _send() -> str:
        # Imported lazily so the module still loads if twilio isn't installed.
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        kwargs: dict = {"from_": from_addr, "to": to_addr}
        if body:
            kwargs["body"] = body
        if media_urls:
            kwargs["media_url"] = media_urls
        return client.messages.create(**kwargs).sid

    return await asyncio.to_thread(_send)


async def send_text_message(params: FunctionCallParams) -> None:
    """Send the user a text message via Twilio (SMS or WhatsApp)."""
    body = ((params.arguments or {}).get("message") or "").strip()
    if not body:
        await params.result_callback({"status": "error", "reason": "empty message"})
        return

    channel = os.environ.get("NORA_TEXT_CHANNEL", "sms").strip().lower()
    try:
        message_sid = await _twilio_send(body)
        logger.info(f"Sent {channel} message {message_sid}")
        await params.result_callback({"status": "sent", "channel": channel, "sid": message_sid})
    except Exception as exc:  # network / auth / unverified-number / not configured
        logger.error(f"send_text_message failed: {exc}")
        await params.result_callback({"status": "error", "reason": str(exc)})


async def send_selfie(params: FunctionCallParams) -> None:
    """Generate a safe-for-work selfie locally and text it to the user.

    Flow: local Stable Diffusion (on the box) -> save the PNG into MEDIA_DIR ->
    hand Twilio the file's PUBLIC url (Twilio lives in the cloud and can't reach
    a private Tailscale/LAN address, so the image must sit at a public
    PUBLIC_MEDIA_BASE_URL, e.g. your Cloudflare tunnel) -> MMS / WhatsApp media.

    The outfit and framing are locked SFW inside imagegen.py; only the benign
    `setting` is caller-tunable.
    """
    setting = ((params.arguments or {}).get("setting") or "").strip()

    media_base = os.environ.get("PUBLIC_MEDIA_BASE_URL", "").rstrip("/")
    media_dir = os.environ.get("MEDIA_DIR", "media")
    if not media_base:
        await params.result_callback(
            {
                "status": "error",
                "reason": (
                    "no public media URL configured — Twilio needs PUBLIC_MEDIA_BASE_URL "
                    "(a Cloudflare-tunneled path); it can't fetch from Tailscale/LAN."
                ),
            }
        )
        return

    try:
        png = await generate_selfie_png(setting)
    except Exception as exc:  # image server down / wrong backend / GPU busy
        logger.error(f"send_selfie image generation failed: {exc}")
        await params.result_callback({"status": "error", "reason": str(exc)})
        return

    # Persist the image where the public web server serves it from.
    os.makedirs(media_dir, exist_ok=True)
    filename = f"selfie-{uuid.uuid4().hex}.png"
    filepath = os.path.join(media_dir, filename)
    try:
        with open(filepath, "wb") as fh:
            fh.write(png)
    except OSError as exc:
        logger.error(f"send_selfie could not write {filepath}: {exc}")
        await params.result_callback({"status": "error", "reason": "could not save image on server"})
        return

    public_url = f"{media_base}/{filename}"
    channel = os.environ.get("NORA_TEXT_CHANNEL", "sms").strip().lower()
    try:
        message_sid = await _twilio_send(body=None, media_urls=[public_url])
        logger.info(f"Sent selfie {message_sid} ({public_url})")
        await params.result_callback({"status": "sent", "channel": channel, "sid": message_sid})
    except Exception as exc:  # network / auth / MMS not supported on number
        logger.error(f"send_selfie delivery failed: {exc}")
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


_send_selfie_schema = FunctionSchema(
    name="send_selfie",
    description=(
        "Text the user a safe-for-work selfie photo of yourself at work. The photo is "
        "always work-appropriate: hospital scrubs, fully clothed, hospital background — the "
        "outfit and framing are fixed and cannot be changed. Use when the user asks for a "
        "photo/selfie or when sharing what you're up to at work would be natural."
    ),
    properties={
        "setting": {
            "type": "string",
            "description": (
                "Optional harmless context for the shot, e.g. \"at the nurses' station\", "
                "\"on a coffee break\", \"by the window\". Purely scene flavor — it does not "
                "and cannot affect the outfit, which stays work-appropriate."
            ),
        },
    },
    required=[],
)


def build_tools_schema() -> ToolsSchema:
    """The full set of tools advertised to the model."""
    return ToolsSchema(
        standard_tools=[_current_time_schema, _send_text_schema, _send_selfie_schema]
    )


def register_tools(llm) -> None:
    """Wire tool names to their async handlers on the LLM service."""
    llm.register_function("get_current_time", get_current_time)
    llm.register_function("send_text_message", send_text_message)
    llm.register_function("send_selfie", send_selfie)
