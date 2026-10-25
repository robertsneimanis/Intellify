"""Format-neutral data passed from parsers to the rest of the pipeline."""

from dataclasses import dataclass, field
from datetime import datetime

Value = float | int | bool | str


class ParseError(Exception):
    """The payload cannot be parsed or does not match its format's schema.

    The message is rejected as a whole.
    """


@dataclass(frozen=True)
class Reading:
    source_field: str  # original key or column name, unchanged
    value: Value  # raw value, before any device-specific scaling
    ts: datetime  # timezone-aware
    register: int | None = None  # Modbus register (WAGO reg_nr), if given


@dataclass
class ParsedMessage:
    external_id: str  # device identity within its format
    model: str | None = None  # explicit model if the payload names one
    manufacturer: str | None = None
    device_type: str | None = None  # payload's own type label, if any
    name: str | None = None
    metadata: dict[str, Value] = field(default_factory=dict)
    readings: list[Reading] = field(default_factory=list)
    # Non-fatal problems (e.g. skipped null values); the message is still stored.
    warnings: list[str] = field(default_factory=list)


@dataclass
class Measurement:
    """A reading with its meaning attached, ready to store."""

    metric_key: str
    channel: str
    ts: datetime
    value: float | bool | str  # scaled to the metric's unit
    source_field: str
    # Reasons the value is implausible; non-empty means quality 'suspect'.
    issues: list[str] = field(default_factory=list)

    @property
    def series(self) -> tuple[str, str]:
        return self.metric_key, self.channel
