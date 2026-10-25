# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a technical assignment (in Latvian), spec in `Tehniskais uzdevums_ Iekārtu datu apstrāde caur MQTT protokolu2.txt`, sample payloads in `*_piemēri.json`. The full pipeline is built and was verified end to end against the docker-compose stack: MQTT publish, broker isolation, queueing while the service is down, a DB outage and recovery, and PM2 start/stop. `README.md` is the reviewer-facing overview and lists the assumptions about device units and scales. The user has no further information on these (2026-10-25), so they are accepted as final unless new device documentation turns up.

## Commands

- `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'`: sets up the dev environment.
- `.venv/bin/pytest`: runs the tests. Run a single one with `.venv/bin/pytest tests/parsers/test_wago.py::test_electric_meter`.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .`: lint and format check.
- `cp .env.example .env && docker compose up -d --wait`: starts RabbitMQ (AMQP 5672, MQTT 1883, management UI http://localhost:15672) and Postgres 17 (5432). Credentials come from `.env` and default to `admin/admin` and `ingest/ingest` with database `telemetry`.
- SQL files in `db/migrations/` run automatically **only on first start** of an empty Postgres volume. To re-apply them, run `docker compose down -v`, which wipes all data. To apply a new file to a running DB: `docker compose exec -T postgres psql -U ingest -d telemetry -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/<file>.sql`.
- The `metrics` catalog is not seeded by SQL. It is synced from the `devices/` modules at service start.
- `.venv/bin/python -m ingest`: runs the service. `.venv/bin/python -m ingest.admin {init,add-tenant,add-building}` provisions the broker and the DB. It needs `AMQP_PASSWORD` and the `RABBITMQ_*` env vars (defaults match `.env.example`).
- `.venv/bin/python scripts/publish_samples.py --username demo:demo-ostas-skati --password ... --building ostas-skati [fixture ...]`: publishes fixtures over MQTT.
- `.venv/bin/python -m ingest.docgen`: regenerates the device tables in `docs/data-model.md`. `tests/test_docs.py` fails when they are stale, so rerun it after changing any device module.
- The integration tests (`tests/integration/`) need the compose Postgres running. They recreate a `telemetry_test` database and skip when Postgres is unreachable.
- `broker/rabbitmq.conf` is mounted as a `conf.d` drop-in. Anonymous MQTT is disabled, and MQTT publishes go to `amq.topic`.

## What the spec requires

The pipeline: devices publish telemetry over MQTT, then Python 3.12 consumes it, validates data quality and stores it in PostgreSQL.

Required components and constraints from the spec:
- **RabbitMQ** with the MQTT plugin is the broker. Several clients (organizations or buildings) share one broker. Each client group needs its own authentication, its own data flow (separate vhosts and/or topic namespaces), and permissions that stop clients from reading each other's topics.
- **PostgreSQL** tables should match the logical structure of each device type. The spec stresses that every stored data point must say clearly what it represents (quantity, unit, meaning), so later visualization doesn't misread it.
- **Python consumer** subscribes to topics, parses each payload, validates it and writes it to the database. It must start automatically on server boot, using PM2 or an equivalent such as systemd.
- **Data quality criteria** must be written down explicitly: values within sane ranges, timestamps in chronological order with no overlaps, schema/format conformance, no duplicates or disallowed values.
- **Bonus:** consume through **AMQP** (durable queues bound to the MQTT topic exchange `amq.topic`) so messages pile up while the script is down. Also bonus: modular code, where adding a device type or data point means adding a parser or schema module rather than editing core logic.

## Sample payload formats

The sample files are **not valid JSON**. They are several JSON documents separated by `## ... ##` banner lines and comments. `python scripts/split_samples.py` splits them into `tests/fixtures/<family>/*.json`, one valid document per file. Regenerate the fixtures with it rather than editing them by hand.

There are three distinct payload families, and each needs its own parser:

1. **Milesight / LoRaWAN (`Milesight_piemēri.json`)**: flat JSON keyed by `devEUI`, with an ISO-8601 UTC `time` (`...Z`). Device models are told apart by their field sets, not by an explicit type field:
   - AM103: environment sensor (`co2`, `temperature`, `humidity`, `battery`).
   - UC300: IO controller. Some keys carry a site prefix (`OstasSkati_*`) and some integer values look scaled (e.g. `hot_side: 2460`). `gpio_*` values are `"on"`/`"off"` strings.
   - Vicki: thermostatic radiator valve, with many boolean status/fault flags and `deviceName`.
   - Zenner SP12: water meter that reports every 3h. `volumes` is an array of `{hour, val}`, where `hour` is just the hour of day (11 means 11:00). The full timestamp has to be rebuilt from the message `time`, including the day rollover across midnight. `hour` is in the building's **local** time, not UTC: the sample's `time` is 09:19Z (12:19 in Riga) and it reports hours 10–12. `val` is a cumulative counter.
2. **Viltrus (`Viltrus_piemēri.json`)**: self-describing. `header.columns` maps numeric column IDs to `name`, `dataType` and `format`. `data[].f[id].v` holds the values, and each row has `ts`. Timestamps have **no timezone**. Device identity comes from `SN` and `name`. Parse by column ID through the header; don't hard-code names.
3. **WAGO-library PLCs (`Wago_piemēri.json`)**: `Lib_version`, `name`, `manufacturer`, `model`, `type` (e.g. `Electric meters`, `PLC`, `AHU`), and optional `serial`/`slave_id`. `DPS` is a list where each item holds **one** arbitrary data-point key plus `ts` and optional `reg_nr` (Modbus register). Timestamps use the IEC format `DT#YYYY-MM-DD-HH:MM:SS` with no timezone. Data-point names can contain spaces (`"max strava"`). For the Corrigo AHU, values are treated as ×10-scaled (`Temp_SupplyAir: 201`), and a raw `0` on sensor inputs as "sensor not connected". This is an accepted assumption; see README "Assumptions".

Field names mix Latvian and English. Keep the original names as source identifiers, and map them to clear canonical metric names and units.

## Architecture

### Layout

- `broker/`: `enabled_plugins` and `rabbitmq.conf`. There is no `definitions.json`: tenants are provisioned at runtime through the management HTTP API by `src/ingest/admin.py`, so no secrets live in the repo.
- `db/migrations/`: plain numbered SQL files (no ORM). `001_init.sql` has not been deployed anywhere, so it can still be edited in place. After the first real deployment, add new numbered files instead.
- `src/ingest/`:
  - `__main__.py` starts one `consumer.VhostConsumer` thread per tenant and re-reads the tenants every `TENANT_REFRESH_SECONDS`.
  - `pipeline.py` handles one message in one transaction: raw → parse → map → validate → store. Rejection logic happens inside a savepoint.
  - `parsers/` has one module per payload family. `devices/` has one module per device model and is auto-discovered (any module with `MODEL`). Shared metrics live in `devices/metrics.py`.
  - `validation.py` holds the plausibility checks, `storage.py` the SQL, `config.py` the env settings, `admin.py` the provisioning CLI and `docgen.py` the docs generator.
- `docs/data-model.md` (device tables generated) and `docs/quality-criteria.md` (hand-written, keep in sync with `validation.py`).
- `ecosystem.config.js` (PM2, which reads `.env`) and `deploy/intellify-ingest.service` (systemd) handle auto-start.

Parsers understand a wire format, and device modules define what fields *mean*. A parser has the signature `parse(payload, tz) -> ParsedMessage` (see `src/ingest/model.py`). It returns raw `Reading`s with timezone-aware timestamps and unscaled values, and raises `ParseError` to reject the whole message. Non-fatal problems go in `ParsedMessage.warnings`. Keep the two separate: a new device on an existing format should only need a new `devices/` module.

Device modules: `Field(pattern, metric, divisor, sentinels)`. The pattern must fullmatch the source field, and a named group `channel` fills `measurements.channel`. The first matching field wins, so put specific patterns before generic ones (for example `Alarm_AckById` before `Alarm_<channel>`). `detect=None` means the model is matched only by an explicit model name. `detect=frozenset()` makes it the catch-all for its format (Viltrus). A metric key must have exactly one definition across all modules, and `devices.catalog()` raises if two differ.

### Broker and isolation

- **Isolation:** one vhost per tenant and one MQTT user `<vhost>-<building>` per building, which devices log in as `<vhost>:<vhost>-<building>`. That user is publish-only: configure `^$`, write `^amq\.topic$`, read `^$`. Its topic write permission is limited to `^<building>\.`. MQTT `/` becomes `.` in AMQP routing keys. The `ingest` service user may only use the `ingest` queue.
- **Topic scheme:** `<building>/<format>/<device_id>`. The `<format>` segment picks the parser; never guess the format from payload content. `<device_id>` may be the device id or its name (WAGO serials contain `+`, an MQTT wildcard). A mismatch is only noted as a warning.
- **Consumption:** over AMQP with sync `pika`. The durable classic queue `ingest` is bound to `amq.topic` with key `#` and is declared by `add-tenant`, so messages are kept from the first publish. It is deliberately not a quorum queue: their default delivery limit would drop messages during a long DB outage. Ack only after the DB commit.

### Database

- `measurements` primary key: `(device_id, metric_id, channel, ts)`. The value goes in exactly one of `value_num`/`value_bool`/`value_text`, already scaled. A `suspect` row requires a `quality_reason`.
- `raw_messages` stores valid JSON in `payload` (jsonb) and anything else in `payload_text`.
- `measurements_readable` is the view intended for visualization.

### Validation policy

See `docs/quality-criteria.md`. In short:
- **Reject the message:** schema or format errors, an unknown building, format or device model.
- **Skip the field with a warning:** no mapping, an unconvertible value, or null.
- **Store as suspect:** `out_of_range`, `sensor_not_connected`, `future_timestamp`, `implausible_timestamp`, `out_of_order`, `counter_decreased`.
- **Drop:** exact duplicates (by primary key).
- **Transient DB or broker errors:** propagate, nothing is acked, and the consumer reconnects with backoff.
- Unexpected exceptions while processing a message are stored as `rejected` with `internal error`, so a bug can't block the queue.
