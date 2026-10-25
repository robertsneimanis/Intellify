"""Helpers shared by the format parsers."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ingest.model import ParseError, Value


def require(payload: dict[str, Any], key: str, kind: type | tuple[type, ...]) -> Any:
    if key not in payload:
        raise ParseError(f"missing field {key!r}")
    value = payload[key]
    if not isinstance(value, kind) or (isinstance(value, bool) and bool not in _as_tuple(kind)):
        raise ParseError(f"field {key!r} has type {type(value).__name__}")
    return value


def _as_tuple(kind: type | tuple[type, ...]) -> tuple[type, ...]:
    return kind if isinstance(kind, tuple) else (kind,)


def is_scalar(value: Any) -> bool:
    return isinstance(value, bool | int | float | str)


def scalar(key: str, value: Any) -> Value:
    if not is_scalar(value):
        raise ParseError(f"field {key!r} is not a scalar value")
    return value


def localize(naive: datetime, tz: ZoneInfo) -> datetime:
    """Attach the building's timezone to a timestamp that has no offset."""
    if naive.tzinfo is not None:
        raise ParseError(f"timestamp {naive.isoformat()} unexpectedly has an offset")
    return naive.replace(tzinfo=tz)
