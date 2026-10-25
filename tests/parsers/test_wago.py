from datetime import datetime

import pytest

from ingest.model import ParseError
from ingest.parsers import parse, wago
from tests.conftest import RIGA


def test_electric_meter(load_fixture):
    message = wago.parse(load_fixture("wago/electric_meters_iem3250.json"), RIGA)

    assert message.external_id == "SK1-P14"  # no serial: falls back to name
    assert (message.manufacturer, message.model, message.device_type) == (
        "Schneider",
        "iEM3250",
        "Electric meters",
    )
    assert message.metadata == {"Lib_version": "v1.2", "slave_id": 1}
    tei = next(r for r in message.readings if r.source_field == "TEI")
    assert (tei.value, tei.register) == (1396.749, 45099)
    assert tei.ts == datetime(2025, 6, 30, 12, 26, 6, tzinfo=RIGA)


def test_plc_uses_serial_and_keeps_spaces(load_fixture):
    message = wago.parse(load_fixture("wago/plc_751_9301.json"), RIGA)

    assert message.external_id.startswith("37SUN")
    assert message.readings[0].source_field == "max strava"
    assert message.readings[0].register is None


def test_ahu_keeps_raw_values(load_fixture):
    message = wago.parse(load_fixture("wago/ahu_e_g3.json"), RIGA)

    readings = {r.source_field: r.value for r in message.readings}
    assert readings["Temp_SupplyAir"] == 201  # x10 scaling is applied by the device module
    assert len(readings) == 26


def point(**extra):
    return {"ts": "DT#2025-06-30-12:26:04"} | extra


def payload(*points):
    return {"name": "N", "model": "M", "type": "PLC", "DPS": list(points)}


@pytest.mark.parametrize(
    "bad",
    [
        payload(point()),  # no data key
        payload(point(a=1, b=2)),  # two data keys
        payload({"a": 1, "ts": "2025-06-30 12:26:04"}),  # not IEC format
        payload(point(a=1, reg_nr="3009")),
        payload(point(a=[1])),
        {"name": "N", "type": "PLC", "DPS": []},  # no model
    ],
)
def test_rejects_malformed(bad):
    with pytest.raises(ParseError):
        wago.parse(bad, RIGA)


def test_dispatch_by_format():
    assert parse("wago", payload(point(a=1)), RIGA).readings[0].value == 1
    with pytest.raises(ParseError):
        parse("modbus", {}, RIGA)
    with pytest.raises(ParseError):
        parse("wago", [1], RIGA)
