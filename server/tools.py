"""Tool (function-calling) scaffold for Nora.

Phase 1 ships one real, dependency-free tool (current time) so the end-to-end
function-calling path is exercised and demonstrable. Add new tools by writing a
handler + a FunctionSchema and registering both in `register_tools` /
`build_tools_schema`. Phase 2 expands this into calendar, CRM, RAG/memory, etc.
"""

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


def build_tools_schema() -> ToolsSchema:
    """The full set of tools advertised to the model."""
    return ToolsSchema(standard_tools=[_current_time_schema])


def register_tools(llm) -> None:
    """Wire tool names to their async handlers on the LLM service."""
    llm.register_function("get_current_time", get_current_time)
