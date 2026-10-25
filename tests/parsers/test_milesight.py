from datetime import UTC, datetime

import pytest

from ingest.model import ParseError
from ingest.parsers import milesight
from tests.conftest import RIGA


def by_field(message):
    return {r.source_field: r for r in message.readings}


def test_am103(load_fixture):
    message = milesight.parse(load_fixture("milesight/am103.json"), RIGA)

    assert message.external_id == "24e124725d021011"
    assert message.model is None  # identified later by its field set
    readings = by_field(message)
    assert set(readings) == {"battery", "co2", "humidity", "temperature"}
    assert readings["co2"].value == 512
    assert readings["co2"].ts == datetime(2025, 6, 30, 12, 32, 42, 315022, tzinfo=UTC)


def test_uc300_keeps_raw_values_and_strings(load_fixture):
    readings = by_field(milesight.parse(load_fixture("milesight/uc300.json"), RIGA))

    assert readings["OstasSkati_hot_side"].value == 2460  # scaling is the device module's job
    assert readings["gpio_in_1"].value == "off"


def test_vicki_name_and_metadata(load_fixture):
    message = milesight.parse(load_fixture("milesight/vicki.json"), RIGA)

    assert message.name == "Vicki-VWMT"
    assert message.metadata == {"applicationID": 5}
    assert by_field(message)["openWindow"].value is False


def test_zenner_hours_are_local_time(load_fixture):
    message = milesight.parse(load_fixture("milesight/zenner.json"), RIGA)

    assert message.model == "ZennerSP12"
    volumes = [r for r in message.readings if r.source_field == "volumes"]
    # Sent 09:19Z = 12:19 Riga (UTC+3), so hours 10..12 are 07:00..09:00 UTC.
    assert [(r.ts.astimezone(UTC).hour, r.value) for r in volumes] == [
        (7, 1024346),
        (8, 1024492),
        (9, 1024673),
    ]


def test_hourly_series_rolls_back_over_midnight():
    payload = {
        "devEUI": "X",
        "time": "2025-06-30T22:30:00Z",  # 01:30 on 1 July in Riga
        "volumes": [{"hour": 23, "val": 1}, {"hour": 0, "val": 2}, {"hour": 1, "val": 3}],
    }
    stamps = [r.ts for r in milesight.parse(payload, RIGA).readings]

    assert stamps == [
        datetime(2025, 6, 30, 23, tzinfo=RIGA),
        datetime(2025, 7, 1, 0, tzinfo=RIGA),
        datetime(2025, 7, 1, 1, tzinfo=RIGA),
    ]


def test_null_values_are_skipped_with_warning():
    message = milesight.parse({"devEUI": "X", "time": "2025-06-30T12:00:00Z", "co2": None}, RIGA)

    assert message.readings == []
    assert message.warnings == ["co2: null value skipped"]


@pytest.mark.parametrize(
    "payload",
    [
        {"time": "2025-06-30T12:00:00Z"},
        {"devEUI": "X"},
        {"devEUI": "X", "time": "2025-06-30T12:00:00"},
        {"devEUI": "X", "time": "yesterday"},
        {"devEUI": "X", "time": "2025-06-30T12:00:00Z", "nested": {"a": 1}},
        {"devEUI": "X", "time": "2025-06-30T12:00:00Z", "volumes": [{"hour": 24, "val": 1}]},
    ],
)
def test_rejects_malformed(payload):
    with pytest.raises(ParseError):
        milesight.parse(payload, RIGA)
