"""Wire-format parsers, one module per payload family.

The format comes from the topic (`<building>/<format>/<device_id>`), not from
guessing at payload content. Each parser turns a decoded JSON payload into a
`ParsedMessage` of raw readings; what the fields mean is decided later by the
`devices/` modules. To support a new format, add a module with
`parse(payload, tz) -> ParsedMessage` and register it here.
"""

from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from ingest.model import ParsedMessage, ParseError
from ingest.parsers import milesight, viltrus, wago

Parser = Callable[[dict[str, Any], ZoneInfo], ParsedMessage]

PARSERS: dict[str, Parser] = {
    "milesight": milesight.parse,
    "viltrus": viltrus.parse,
    "wago": wago.parse,
}


def parse(source_format: str, payload: Any, tz: ZoneInfo) -> ParsedMessage:
    parser = PARSERS.get(source_format)
    if parser is None:
        raise ParseError(f"unknown format {source_format!r}")
    if not isinstance(payload, dict):
        raise ParseError("payload must be a JSON object")
    return parser(payload, tz)
