import json
from datetime import UTC, datetime

import pytest

from ingest.pipeline import Pipeline
from tests.conftest import FIXTURES

NOW = datetime(2025, 7, 1, tzinfo=UTC)
SAMPLES = {
    "milesight/am103.json": 4,
    "milesight/uc300.json": 15,
    "milesight/vicki.json": 15,
    "milesight/zenner.json": 4,
    "viltrus/el_uzskaite_3.json": 19,
    "wago/electric_meters_iem3250.json": 5,
    "wago/plc_751_9301.json": 5,
    "wago/ahu_e_g3.json": 26,
}


@pytest.fixture
def pipeline(conn, metric_ids):
    return Pipeline(conn, metric_ids, clock=lambda: NOW)


def body(name, **changes):
    payload = json.loads((FIXTURES / name).read_text()) | changes
    return json.dumps(payload).encode()


def send(pipeline, name, device="dev", **changes):
    fmt = name.split("/")[0]
    return pipeline.handle("demo", f"ostas-skati.{fmt}.{device}", body(name, **changes))


def rows(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


@pytest.mark.parametrize("name", SAMPLES)
def test_samples_are_stored(pipeline, conn, name):
    outcome = send(pipeline, name)

    assert outcome.status == "processed"
    assert outcome.stored == SAMPLES[name]
    assert rows(conn, "SELECT status FROM raw_messages") == [("processed",)]


def test_readable_view_has_meaning_and_local_time(pipeline, conn):
    send(pipeline, "milesight/uc300.json", device="24e124445d226973")

    row = rows(
        conn,
        "SELECT device_type, metric, channel, unit, value_num, ts_local::text"
        " FROM measurements_readable WHERE source_field = 'OstasSkati_hot_side'",
    )
    assert row == [
        (
            "io_controller",
            "heat_supply_temperature",
            "OstasSkati",
            "°C",
            24.6,
            "2025-06-30 15:33:10.709277",
        ),
    ]


def test_topic_and_payload_id_mismatch_is_noted(pipeline):
    outcome = send(pipeline, "milesight/am103.json", device="other")

    assert outcome.status == "processed"
    assert any("differs from payload id" in e for e in outcome.errors)


def test_redelivered_message_stores_nothing_twice(pipeline, conn):
    send(pipeline, "wago/electric_meters_iem3250.json")
    again = send(pipeline, "wago/electric_meters_iem3250.json")

    assert again.stored == 0
    assert "5 readings were already stored" in again.errors[-1]
    assert rows(conn, "SELECT count(*) FROM measurements") == [(5,)]
    assert rows(conn, "SELECT count(*) FROM devices") == [(1,)]


def test_unconnected_ahu_sensors_are_suspect(pipeline, conn):
    send(pipeline, "wago/ahu_e_g3.json")

    suspect = rows(
        conn,
        "SELECT source_field, quality_reason FROM measurements"
        " WHERE quality = 'suspect' ORDER BY source_field",
    )
    assert ("Temp_Room1", "sensor_not_connected") in suspect
    assert ("Temp_SupplyAir", "sensor_not_connected") not in suspect


def test_decreasing_counter_across_messages_is_suspect(pipeline, conn):
    first = json.loads((FIXTURES / "milesight/zenner.json").read_text())
    later = first | {
        "time": "2025-06-30T12:19:46Z",
        "volumes": [{"hour": 13, "val": 1024000}],  # lower than 1024673 at 12:00
    }
    pipeline.handle("demo", "ostas-skati.milesight.x", json.dumps(first).encode())
    pipeline.handle("demo", "ostas-skati.milesight.x", json.dumps(later).encode())

    assert rows(
        conn, "SELECT quality, quality_reason FROM measurements WHERE value_num = 1024.0"
    ) == [("suspect", "counter_decreased")]


@pytest.mark.parametrize(
    ("routing_key", "raw", "reason"),
    [
        ("ostas-skati.wago.x", b"{not json", "not valid UTF-8 JSON"),
        ("ostas-skati.wago.x", b'{"name": "N"}', "missing field 'model'"),
        ("ostas-skati.modbus.x", b"{}", "unknown format 'modbus'"),
        ("elsewhere.wago.x", b"{}", "unknown building 'elsewhere'"),
        ("ostas-skati.wago", b"{}", "is not <building>/<format>/<device_id>"),
        (
            "ostas-skati.milesight.x",
            b'{"devEUI": "x", "time": "2025-06-30T12:00:00Z", "foo": 1}',
            "cannot identify",
        ),
    ],
)
def test_bad_messages_are_rejected_and_kept(pipeline, conn, routing_key, raw, reason):
    outcome = pipeline.handle("demo", routing_key, raw)

    assert outcome.status == "rejected"
    assert reason in outcome.errors[-1]
    status, errors, text = rows(conn, "SELECT status, errors, payload_text FROM raw_messages")[0]
    assert status == "rejected" and reason in errors[-1]
    assert rows(conn, "SELECT count(*) FROM measurements") == [(0,)]
    if raw.startswith(b"{not"):
        assert text == "{not json"


def test_rejection_rolls_back_partial_work(pipeline, conn, monkeypatch):
    from ingest import storage

    def boom(*args):
        raise ValueError("bug")

    monkeypatch.setattr(storage, "insert_measurements", boom)
    outcome = send(pipeline, "milesight/am103.json")

    assert outcome.status == "rejected" and "internal error" in outcome.errors[-1]
    assert rows(conn, "SELECT count(*) FROM devices") == [(0,)]
