"""Building blocks for device modules: what a metric is and how a field maps to it."""

import re
from dataclasses import dataclass, field
from typing import Literal

from ingest.model import Value

ValueType = Literal["numeric", "boolean", "text"]
Kind = Literal["gauge", "counter", "state"]


@dataclass(frozen=True)
class Metric:
    """A canonical data point meaning; one row in the `metrics` table."""

    key: str
    quantity: str
    unit: str | None
    value_type: ValueType
    kind: Kind  # gauge: instantaneous; counter: cumulative, never decreases; state: status/mode
    description: str
    min_valid: float | None = None
    max_valid: float | None = None


@dataclass(frozen=True)
class Field:
    """Maps source fields matching `pattern` to a metric.

    `pattern` must match the whole source field name. A named group `channel`
    tells apart identical inputs on one device (e.g. `pt100_(?P<channel>\\d)`).
    """

    pattern: str
    metric: Metric
    divisor: float = 1  # stored value = raw / divisor, e.g. 10 for a x10-scaled register
    # Raw values the device sends when it has no real reading (e.g. 0 for an
    # unconnected sensor). They are stored but flagged as suspect.
    sentinels: frozenset[Value] = frozenset()
    regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "regex", re.compile(self.pattern))


@dataclass(frozen=True)
class DeviceModel:
    """Everything the pipeline needs to know about one device model."""

    source_format: str  # parser that delivers its payloads
    model: str  # matches ParsedMessage.model when the payload names it
    device_type: str
    manufacturer: str | None
    description: str
    fields: tuple[Field, ...]
    # For payloads that do not name their model: the fields that identify it.
    # None: only matched by explicit model name. Empty set: catch-all for its format.
    detect: frozenset[str] | None = None
    # Source fields that are known but are not measurements (identity, firmware flags).
    ignore: frozenset[str] = frozenset()

    def match(self, source_field: str) -> tuple[Field, str] | None:
        for f in self.fields:
            if m := f.regex.fullmatch(source_field):
                return f, (m.groupdict().get("channel") or "")
        return None
