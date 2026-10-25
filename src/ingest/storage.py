"""PostgreSQL access. All functions run inside the caller's transaction."""

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from ingest.devices.base import DeviceModel, Metric
from ingest.model import Measurement, ParsedMessage


def sync_metrics(conn: psycopg.Connection, metrics: Iterable[Metric]) -> dict[str, int]:
    """Upsert the metric catalog from the device modules; return key -> id."""
    ids = {}
    for m in metrics:
        row = conn.execute(
            """
            INSERT INTO metrics (key, quantity, unit, value_type, kind, description,
                                 min_valid, max_valid)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET
                quantity = EXCLUDED.quantity, unit = EXCLUDED.unit,
                value_type = EXCLUDED.value_type, kind = EXCLUDED.kind,
                description = EXCLUDED.description,
                min_valid = EXCLUDED.min_valid, max_valid = EXCLUDED.max_valid
            RETURNING id
            """,
            (
                m.key,
                m.quantity,
                m.unit,
                m.value_type,
                m.kind,
                m.description,
                m.min_valid,
                m.max_valid,
            ),
        ).fetchone()
        ids[m.key] = row[0]
    return ids


def tenant_vhosts(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT vhost FROM tenants ORDER BY vhost")]


def find_building(conn: psycopg.Connection, vhost: str, slug: str) -> tuple[int, ZoneInfo] | None:
    row = conn.execute(
        """
        SELECT b.id, b.timezone FROM buildings b JOIN tenants t ON t.id = b.tenant_id
        WHERE t.vhost = %s AND b.slug = %s
        """,
        (vhost, slug),
    ).fetchone()
    return (row[0], ZoneInfo(row[1])) if row else None


def insert_raw(
    conn: psycopg.Connection, vhost: str, routing_key: str, payload: Any, text: str | None
) -> int:
    """Store an incoming message. `payload` is the decoded JSON, or `text` if decoding failed."""
    sql = """
        INSERT INTO raw_messages (vhost, routing_key, payload, payload_text)
        VALUES (%s, %s, %s, %s) RETURNING id
    """
    if text is None:
        try:
            with conn.transaction():
                return conn.execute(sql, (vhost, routing_key, Jsonb(payload), None)).fetchone()[0]
        except psycopg.DataError:  # JSON that jsonb refuses, e.g. a \u0000 escape
            text = json.dumps(payload, ensure_ascii=False)
    return conn.execute(sql, (vhost, routing_key, None, text.replace("\x00", ""))).fetchone()[0]


def get_raw(conn: psycopg.Connection, raw_id: int) -> tuple[str, str, Any, str | None]:
    """(vhost, routing_key, payload, payload_text) of a stored message; locks the row."""
    row = conn.execute(
        "SELECT vhost, routing_key, payload, payload_text FROM raw_messages"
        " WHERE id = %s FOR UPDATE",
        (raw_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"raw message {raw_id} not found")
    return row


def raw_ids(conn: psycopg.Connection, status: str | None) -> list[int]:
    """Ids of stored messages, oldest first, optionally only those with `status`."""
    rows = conn.execute(
        "SELECT id FROM raw_messages WHERE %(status)s::text IS NULL OR status = %(status)s"
        " ORDER BY id",
        {"status": status},
    )
    return [r[0] for r in rows]


def delete_measurements_of(conn: psycopg.Connection, raw_id: int) -> None:
    conn.execute("DELETE FROM measurements WHERE raw_message_id = %s", (raw_id,))


def finish_raw(conn: psycopg.Connection, raw_id: int, status: str, errors: list[str]) -> None:
    conn.execute(
        "UPDATE raw_messages SET status = %s, errors = %s, processed_at = now() WHERE id = %s",
        (status, Jsonb(errors), raw_id),
    )


def upsert_device(
    conn: psycopg.Connection,
    building_id: int,
    source_format: str,
    message: ParsedMessage,
    model: DeviceModel,
) -> int:
    metadata = dict(message.metadata)
    if message.device_type:
        metadata["source_type"] = message.device_type
    return conn.execute(
        """
        INSERT INTO devices (building_id, source_format, external_id, model, manufacturer,
                             device_type, name, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (building_id, source_format, external_id) DO UPDATE SET
            model = EXCLUDED.model,
            manufacturer = EXCLUDED.manufacturer,
            device_type = EXCLUDED.device_type,
            name = COALESCE(EXCLUDED.name, devices.name),
            metadata = devices.metadata || EXCLUDED.metadata,
            last_seen = now()
        RETURNING id
        """,
        (
            building_id,
            source_format,
            message.external_id,
            model.model,
            message.manufacturer or model.manufacturer,
            model.device_type,
            message.name,
            Jsonb(metadata),
        ),
    ).fetchone()[0]


def latest_values(
    conn: psycopg.Connection, device_id: int, metric_ids: Mapping[str, int]
) -> dict[tuple[str, str], tuple[datetime, float | bool | str]]:
    """Newest stored (ts, value) for every series of a device."""
    keys = {v: k for k, v in metric_ids.items()}
    rows = conn.execute(
        """
        SELECT DISTINCT ON (metric_id, channel)
               metric_id, channel, ts, value_num, value_bool, value_text
        FROM measurements WHERE device_id = %s
        ORDER BY metric_id, channel, ts DESC
        """,
        (device_id,),
    )
    return {
        (keys[metric_id], channel): (ts, next(v for v in (num, flag, text) if v is not None))
        for metric_id, channel, ts, num, flag, text in rows
        if metric_id in keys
    }


def insert_measurements(
    conn: psycopg.Connection,
    device_id: int,
    raw_id: int,
    measurements: list[Measurement],
    metric_ids: Mapping[str, int],
) -> int:
    """Insert measurements, skipping ones already stored. Returns the number inserted."""
    inserted = 0
    for m in measurements:
        num = m.value if isinstance(m.value, float) else None
        flag = m.value if isinstance(m.value, bool) else None
        text = m.value if isinstance(m.value, str) else None
        cur = conn.execute(
            """
            INSERT INTO measurements (device_id, metric_id, channel, ts, value_num, value_bool,
                                      value_text, quality, quality_reason, source_field,
                                      raw_message_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                device_id,
                metric_ids[m.metric_key],
                m.channel,
                m.ts,
                num,
                flag,
                text,
                "suspect" if m.issues else "good",
                ",".join(m.issues) or None,
                m.source_field,
                raw_id,
            ),
        )
        inserted += cur.rowcount
    return inserted
