"""Milesight / LoRaWAN network-server JSON.

Flat object keyed by `devEUI` with an ISO-8601 UTC `time`. Every other scalar
key is a reading taken at `time`. A list of `{hour, val}` objects (Zenner
`volumes`) is an hourly series: `hour` is the hour of day in the building's
local time, at or before the message time.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ingest.model import ParsedMessage, ParseError, Reading
from ingest.parsers._common import is_scalar, require

# Keys that identify the device rather than measure something.
METADATA_KEYS = {"applicationID"}


def parse(payload: dict[str, Any], tz: ZoneInfo) -> ParsedMessage:
    dev_eui = require(payload, "devEUI", str)
    ts = _parse_time(require(payload, "time", str))
    message = ParsedMessage(
        external_id=dev_eui.lower(),
        model=payload.get("device"),
        name=payload.get("deviceName"),
    )

    for key, value in payload.items():
        if key in {"devEUI", "time", "device", "deviceName"}:
            continue
        if key in METADATA_KEYS:
            message.metadata[key] = value
        elif value is None:
            message.warnings.append(f"{key}: null value skipped")
        elif is_scalar(value):
            message.readings.append(Reading(key, value, ts))
        elif isinstance(value, list):
            message.readings.extend(_hourly_series(key, value, ts, tz))
        else:
            raise ParseError(f"field {key!r} has unsupported type {type(value).__name__}")
    return message


def _parse_time(text: str) -> datetime:
    try:
        ts = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ParseError(f"invalid time {text!r}") from exc
    if ts.tzinfo is None:
        raise ParseError(f"time {text!r} has no timezone")
    return ts


def _hourly_series(key: str, items: list[Any], sent: datetime, tz: ZoneInfo) -> list[Reading]:
    sent_local = sent.astimezone(tz)
    readings = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"hour", "val"}:
            raise ParseError(f"{key!r} items must be objects with 'hour' and 'val'")
        hour, val = item["hour"], item["val"]
        if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
            raise ParseError(f"{key!r} has invalid hour {hour!r}")
        if not is_scalar(val) or isinstance(val, bool | str):
            raise ParseError(f"{key!r} has non-numeric val {val!r}")
        ts = sent_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if ts > sent_local:  # hour is from before midnight
            ts -= timedelta(days=1)  # aware arithmetic keeps the local wall clock
        readings.append(Reading(key, val, ts))
    return readings
