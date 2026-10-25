"""Processing of one message: raw -> parse -> map -> validate -> store.

Each message is handled in a single database transaction, so the caller can
acknowledge it to RabbitMQ once `handle` returns. A message that cannot be
used is stored with status 'rejected' and its reasons; only database
connection errors propagate, so the message stays in the queue.
"""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg

from ingest import devices, parsers, storage, validation
from ingest.devices.base import Metric
from ingest.model import ParseError

log = logging.getLogger(__name__)


class Rejected(Exception):
    """The message cannot be processed; stored as rejected with this reason."""


@dataclass
class Outcome:
    raw_id: int
    status: str  # 'processed' or 'rejected'
    stored: int = 0
    suspect: int = 0
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        conn: psycopg.Connection,
        metric_ids: Mapping[str, int],
        metrics: Mapping[str, Metric] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.conn = conn
        self.metric_ids = metric_ids
        self.metrics = metrics if metrics is not None else devices.catalog()
        self.clock = clock

    def handle(self, vhost: str, routing_key: str, body: bytes) -> Outcome:
        with self.conn.transaction():
            payload, text = _decode(body)
            raw_id = storage.insert_raw(self.conn, vhost, routing_key, payload, text)
            outcome = Outcome(raw_id, "processed")
            try:
                with self.conn.transaction():  # savepoint: undo partial work on rejection
                    if text is not None:
                        raise Rejected("body is not valid UTF-8 JSON")
                    self._process(vhost, routing_key, payload, outcome)
            except (Rejected, ParseError, devices.UnknownDevice) as exc:
                outcome = Outcome(raw_id, "rejected", errors=[*outcome.errors, str(exc)])
            except psycopg.OperationalError:
                raise
            except Exception as exc:  # a bug must not block the queue; keep the message
                log.exception("unexpected error processing raw message %s", raw_id)
                outcome = Outcome(raw_id, "rejected", errors=[f"internal error: {exc!r}"])
            storage.finish_raw(self.conn, raw_id, outcome.status, outcome.errors)
        return outcome

    def _process(self, vhost: str, routing_key: str, payload: object, outcome: Outcome) -> None:
        building_slug, source_format, topic_device = _split_routing_key(routing_key)
        building = storage.find_building(self.conn, vhost, building_slug)
        if building is None:
            raise Rejected(f"unknown building {building_slug!r} for tenant {vhost!r}")
        building_id, tz = building

        message = parsers.parse(source_format, payload, tz)
        model = devices.resolve(source_format, message)
        outcome.errors.extend(message.warnings)
        # The topic may carry the device id or its name (a serial can contain MQTT wildcards).
        if topic_device.lower() not in {message.external_id.lower(), (message.name or "").lower()}:
            outcome.errors.append(
                f"topic device id {topic_device!r} differs from payload id {message.external_id!r}"
            )

        device_id = storage.upsert_device(self.conn, building_id, source_format, message, model)
        measurements, warnings = devices.to_measurements(model, message.readings)
        outcome.errors.extend(warnings)
        latest = storage.latest_values(self.conn, device_id, self.metric_ids)
        measurements, warnings = validation.assess(measurements, self.metrics, latest, self.clock())
        outcome.errors.extend(warnings)

        outcome.stored = storage.insert_measurements(
            self.conn, device_id, outcome.raw_id, measurements, self.metric_ids
        )
        outcome.suspect = sum(1 for m in measurements if m.issues)
        if skipped := len(measurements) - outcome.stored:
            outcome.errors.append(f"{skipped} readings were already stored, skipped as duplicates")


def _decode(body: bytes) -> tuple[object, str | None]:
    """Return (payload, None) for valid JSON, else (None, body as text)."""
    try:
        return json.loads(body.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, body.decode("utf-8", errors="replace")


def _split_routing_key(routing_key: str) -> tuple[str, str, str]:
    # MQTT topic <building>/<format>/<device_id> arrives as building.format.device_id.
    parts = routing_key.split(".")
    if len(parts) != 3 or not all(parts):
        raise Rejected(f"topic {routing_key!r} is not <building>/<format>/<device_id>")
    return parts[0], parts[1], parts[2]
