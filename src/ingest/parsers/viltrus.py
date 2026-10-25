"""Viltrus self-describing export.

`header.columns` maps column IDs to name/dataType/format; each row in `data`
has a naive local `ts` and values under `f[<column id>].v`. Values are looked
up through the header, never by hard-coded column names.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ingest.model import ParsedMessage, ParseError, Reading
from ingest.parsers._common import localize, require, scalar

NUMERIC_TYPES = {"NUMBER"}


def parse(payload: dict[str, Any], tz: ZoneInfo) -> ParsedMessage:
    serial = require(payload, "SN", str | int)
    header = require(payload, "header", dict)
    columns = require(header, "columns", dict)
    rows = require(payload, "data", list)
    message = ParsedMessage(external_id=str(serial), name=payload.get("name"))

    expected = header.get("recordCount")
    if expected is not None and expected != len(rows):
        message.warnings.append(f"recordCount is {expected} but data has {len(rows)} rows")

    for row in rows:
        if not isinstance(row, dict):
            raise ParseError("data rows must be objects")
        ts = localize(_parse_ts(require(row, "ts", str)), tz)
        for col_id, cell in require(row, "f", dict).items():
            column = columns.get(col_id)
            if not isinstance(column, dict) or "name" not in column:
                raise ParseError(f"value for column {col_id!r} not described in header")
            name = column["name"]
            if not isinstance(cell, dict) or "v" not in cell:
                raise ParseError(f"column {name!r} cell has no 'v'")
            if cell["v"] is None:
                message.warnings.append(f"{name}: null value skipped")
                continue
            value = scalar(name, cell["v"])
            if column.get("dataType") in NUMERIC_TYPES and isinstance(value, bool | str):
                raise ParseError(f"column {name!r} is NUMBER but value is {value!r}")
            message.readings.append(Reading(name, value, ts))
    return message


def _parse_ts(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ParseError(f"invalid ts {text!r}") from exc
