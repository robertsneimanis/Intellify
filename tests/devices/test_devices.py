from datetime import UTC, datetime

import pytest

from ingest import devices, parsers
from ingest.devices.base import DeviceModel, Field, Metric
from ingest.model import ParsedMessage, Reading
from tests.conftest import RIGA

TS = datetime(2025, 6, 30, 12, tzinfo=UTC)
FIXTURE_MODELS = {
    "milesight/am103.json": "AM103",
    "milesight/uc300.json": "UC300",
    "milesight/vicki.json": "Vicki",
    "milesight/zenner.json": "ZennerSP12",
    "viltrus/el_uzskaite_3.json": "Viltrus",
    "wago/electric_meters_iem3250.json": "iEM3250",
    "wago/plc_751_9301.json": "751-9301",
    "wago/ahu_e_g3.json": "E_G3",
}


def measure(load_fixture, name):
    fmt = name.split("/")[0]
    message = parsers.parse(fmt, load_fixture(name), RIGA)
    model = devices.resolve(fmt, message)
    measurements, warnings = devices.to_measurements(model, message.readings)
    return model, {(m.source_field, m.ts): m for m in measurements}, warnings


@pytest.mark.parametrize("name", FIXTURE_MODELS)
def test_every_sample_field_is_mapped(load_fixture, name):
    model, _, warnings = measure(load_fixture, name)

    assert model.model == FIXTURE_MODELS[name]
    assert warnings == []


def value(measurements, field):
    return next(m for (f, _), m in measurements.items() if f == field)


def test_uc300_heat_meter_scaling_and_channels(load_fixture):
    _, ms, _ = measure(load_fixture, "milesight/uc300.json")

    hot = value(ms, "OstasSkati_hot_side")
    assert (hot.metric_key, hot.channel, hot.value) == (
        "heat_supply_temperature",
        "OstasSkati",
        24.6,
    )
    assert value(ms, "OstasSkati_temp_diff").value == -0.2
    assert (value(ms, "gpio_in_3").channel, value(ms, "gpio_in_3").value) == ("3", False)


def test_zenner_litres_to_cubic_metres(load_fixture):
    _, ms, _ = measure(load_fixture, "milesight/zenner.json")

    volumes = sorted((m.ts, m.value) for m in ms.values() if m.metric_key == "water_volume")
    assert [v for _, v in volumes] == [1024.346, 1024.492, 1024.673]


def test_viltrus_channels_ignore_case(load_fixture):
    _, ms, _ = measure(load_fixture, "viltrus/el_uzskaite_3.json")

    assert value(ms, "SK1_kopeja_jauda").channel == "SK1"
    assert value(ms, "Sk1_aktiva_jauda").metric_key == "active_power"
    assert value(ms, "61_frekvence").value == 50.01
    assert value(ms, "61_imports").value == 389613.288


def test_ahu_scaling_and_unconnected_sensors(load_fixture):
    _, ms, _ = measure(load_fixture, "wago/ahu_e_g3.json")

    supply = value(ms, "Temp_SupplyAir")
    assert (supply.value, supply.issues) == (20.1, [])
    room = value(ms, "Temp_Room2")
    assert (room.metric_key, room.channel, room.issues) == (
        "room_temperature",
        "2",
        ["sensor_not_connected"],
    )
    assert value(ms, "Alarm_AckById").metric_key == "ahu_alarm_ack_by"
    assert (value(ms, "Alarm_Fire").channel, value(ms, "Alarm_Fire").value) == ("Fire", False)


def test_meter_serial_is_ignored_not_warned(load_fixture):
    _, ms, warnings = measure(load_fixture, "wago/electric_meters_iem3250.json")

    assert "SN" not in {f for f, _ in ms}
    assert warnings == []


def test_unmapped_and_unconvertible_fields_warn():
    model = devices.resolve("milesight", ParsedMessage("x", model="ZennerSP12"))
    readings = [Reading("mystery", 1, TS), Reading("ok", "maybe", TS), Reading("ok", 1, TS)]

    measurements, warnings = devices.to_measurements(model, readings)

    assert [m.value for m in measurements] == [True]
    assert warnings == [
        "mystery: no mapping in ZennerSP12, not stored",
        "ok: expected an on/off value, got 'maybe', not stored",
    ]


def test_unknown_models_are_rejected():
    with pytest.raises(devices.UnknownDevice):
        devices.resolve("wago", ParsedMessage("x", model="NoSuchPLC"))
    with pytest.raises(devices.UnknownDevice):
        devices.resolve("milesight", ParsedMessage("x", readings=[Reading("foo", 1, TS)]))


def test_catalog_refuses_conflicting_definitions():
    a = Metric("t", "temperature", "°C", "numeric", "gauge", "A")
    b = Metric("t", "temperature", "K", "numeric", "gauge", "B")
    models = [
        DeviceModel("wago", m, "plc", None, "", (Field("x", metric),))
        for m, metric in (("a", a), ("b", b))
    ]
    with pytest.raises(ValueError, match="defined differently"):
        devices.catalog(models)


def test_real_catalog_is_consistent():
    catalog = devices.catalog()
    for metric in catalog.values():
        if metric.value_type != "numeric":
            assert metric.min_valid is None and metric.max_valid is None, metric.key
