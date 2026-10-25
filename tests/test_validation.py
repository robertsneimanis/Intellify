from datetime import UTC, datetime, timedelta

from ingest import validation as v
from ingest.devices.base import Metric
from ingest.model import Measurement

NOW = datetime(2025, 6, 30, 12, tzinfo=UTC)
METRICS = {
    "temp": Metric("temp", "temperature", "°C", "numeric", "gauge", "t", -20, 60),
    "energy": Metric("energy", "energy", "kWh", "numeric", "counter", "e", 0, None),
    "flag": Metric("flag", "state", None, "boolean", "state", "f"),
}


def m(metric="temp", value=20.0, minutes=0, channel="", field="f"):
    return Measurement(metric, channel, NOW + timedelta(minutes=minutes), value, field)


def issues(measurements, latest=None):
    kept, _ = v.assess(measurements, METRICS, latest or {}, NOW)
    return [x.issues for x in kept]


def test_plausible_values_pass():
    assert issues([m(), m("energy", 5.0), m("flag", True)]) == [[], [], []]


def test_range_limits():
    assert issues([m(value=-20.1), m(value=60.1, minutes=-1), m(value=60, minutes=-2)]) == [
        [],
        [v.OUT_OF_RANGE],
        [v.OUT_OF_RANGE],
    ]  # sorted by ts: 60 (ok), 60.1, -20.1


def test_future_and_ancient_timestamps():
    assert issues([m(minutes=4), m(minutes=6)]) == [[], [v.FUTURE_TIMESTAMP]]
    ancient = Measurement("temp", "", datetime(1970, 1, 1, tzinfo=UTC), 20.0, "f")
    assert issues([ancient]) == [[v.IMPLAUSIBLE_TIMESTAMP]]


def test_older_than_stored_is_out_of_order():
    latest = {("temp", ""): (NOW, 20.0)}
    assert issues([m(minutes=-10), m(minutes=3)], latest) == [[v.OUT_OF_ORDER], []]


def test_counter_must_not_decrease():
    latest = {("energy", ""): (NOW - timedelta(hours=1), 100.0)}
    result = issues([m("energy", 99.0), m("energy", 101.0, minutes=1)], latest)
    assert result == [[v.COUNTER_DECREASED], []]


def test_counter_checked_within_message_in_time_order():
    result = issues([m("energy", 5.0, minutes=2), m("energy", 6.0, minutes=1)])
    assert result == [[], [v.COUNTER_DECREASED]]


def test_series_are_independent_per_channel():
    latest = {("energy", "a"): (NOW - timedelta(hours=1), 100.0)}
    assert issues([m("energy", 1.0, channel="b")], latest) == [[]]


def test_duplicates_within_message():
    kept, warnings = v.assess([m(value=1.0), m(value=1.0), m(value=2.0)], METRICS, {}, NOW)

    assert [x.value for x in kept] == [1.0]
    assert len(warnings) == 1 and "conflicting values 1.0 and 2.0" in warnings[0]


def test_sentinel_issue_from_mapping_is_kept():
    x = m()
    x.issues.append(v.SENSOR_NOT_CONNECTED)
    assert issues([x]) == [[v.SENSOR_NOT_CONNECTED]]
