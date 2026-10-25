"""Data quality checks on mapped measurements.

Schema and format problems are caught earlier by the parsers and reject the
whole message. The checks here judge plausibility: a failing measurement is
still stored, but with quality 'suspect' and the reasons below. Nothing is
dropped except exact repeats of a reading, which are duplicates by definition.
See docs/quality-criteria.md.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from ingest.devices.base import Metric
from ingest.model import Measurement

# Issue codes stored in measurements.quality_reason.
OUT_OF_RANGE = "out_of_range"
FUTURE_TIMESTAMP = "future_timestamp"
IMPLAUSIBLE_TIMESTAMP = "implausible_timestamp"
OUT_OF_ORDER = "out_of_order"
COUNTER_DECREASED = "counter_decreased"
SENSOR_NOT_CONNECTED = "sensor_not_connected"  # set by device mapping (sentinel values)

CLOCK_TOLERANCE = timedelta(minutes=5)  # allowed device clock drift into the future
EARLIEST_VALID = datetime(2015, 1, 1, tzinfo=UTC)  # older means an unset device clock

Series = tuple[str, str]  # (metric key, channel)
Latest = Mapping[Series, tuple[datetime, float | bool | str]]


def assess(
    measurements: list[Measurement],
    metrics: Mapping[str, Metric],
    latest: Latest,
    now: datetime,
) -> tuple[list[Measurement], list[str]]:
    """Flag implausible measurements and drop in-message duplicates.

    `latest` holds the newest stored (ts, value) per series of this device.
    Returns the measurements to store and message-level warnings.
    """
    kept: list[Measurement] = []
    warnings: list[str] = []
    seen: dict[tuple[Series, datetime], Measurement] = {}
    last = dict(latest)

    for m in sorted(measurements, key=lambda m: m.ts):
        key = (m.series, m.ts)
        if (first := seen.get(key)) is not None:
            if first.value != m.value:
                warnings.append(
                    f"{m.source_field}: conflicting values {first.value!r} and {m.value!r} "
                    f"at {m.ts.isoformat()}, kept the first"
                )
            continue
        seen[key] = m

        metric = metrics[m.metric_key]
        _check_range(m, metric)
        _check_timestamp(m, now)

        previous = last.get(m.series)
        if previous is not None:
            prev_ts, prev_value = previous
            if m.ts < prev_ts:
                m.issues.append(OUT_OF_ORDER)
            elif m.ts > prev_ts and metric.kind == "counter" and m.value < prev_value:
                m.issues.append(COUNTER_DECREASED)
        if previous is None or m.ts > previous[0]:
            last[m.series] = (m.ts, m.value)
        kept.append(m)
    return kept, warnings


def _check_range(m: Measurement, metric: Metric) -> None:
    if metric.value_type != "numeric":
        return
    if metric.min_valid is not None and m.value < metric.min_valid:
        m.issues.append(OUT_OF_RANGE)
    elif metric.max_valid is not None and m.value > metric.max_valid:
        m.issues.append(OUT_OF_RANGE)


def _check_timestamp(m: Measurement, now: datetime) -> None:
    if m.ts > now + CLOCK_TOLERANCE:
        m.issues.append(FUTURE_TIMESTAMP)
    elif m.ts < EARLIEST_VALID:
        m.issues.append(IMPLAUSIBLE_TIMESTAMP)
