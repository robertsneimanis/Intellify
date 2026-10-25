"""WAGO library PLC payload.

Device header (`name`, `manufacturer`, `model`, `type`, optional `serial`,
`slave_id`) plus `DPS`: a list of single data points, each holding exactly one
data key, an IEC timestamp `DT#YYYY-MM-DD-HH:MM:SS` (naive, building local
time) and an optional Modbus `reg_nr`.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ingest.model import ParsedMessage, ParseError, Reading
from ingest.parsers._common import localize, require, scalar

DP_RESERVED = {"ts", "reg_nr"}


def parse(payload: dict[str, Any], tz: ZoneInfo) -> ParsedMessage:
    name = require(payload, "name", str)
    serial = payload.get("serial")
    message = ParsedMessage(
        # The PLC name is the fallback identity for devices without a serial (meters).
        external_id=str(serial) if serial else name,
        model=require(payload, "model", str),
        manufacturer=payload.get("manufacturer"),
        device_type=require(payload, "type", str),
        name=name,
        metadata={k: payload[k] for k in ("Lib_version", "slave_id", "serial") if k in payload},
    )

    for point in require(payload, "DPS", list):
        if not isinstance(point, dict):
            raise ParseError("DPS items must be objects")
        keys = [k for k in point if k not in DP_RESERVED]
        if len(keys) != 1:
            raise ParseError(f"DPS item must hold exactly one data point, got {keys}")
        key = keys[0]
        register = point.get("reg_nr")
        if register is not None and (not isinstance(register, int) or isinstance(register, bool)):
            raise ParseError(f"{key!r} has invalid reg_nr {register!r}")
        ts = localize(parse_iec_datetime(require(point, "ts", str)), tz)
        if point[key] is None:
            message.warnings.append(f"{key}: null value skipped")
            continue
        message.readings.append(Reading(key, scalar(key, point[key]), ts, register))
    return message


def parse_iec_datetime(text: str) -> datetime:
    """Parse IEC 61131-3 `DT#2025-06-30-12:26:04`."""
    try:
        return datetime.strptime(text, "DT#%Y-%m-%d-%H:%M:%S")
    except ValueError as exc:
        raise ParseError(f"invalid IEC timestamp {text!r}") from exc
