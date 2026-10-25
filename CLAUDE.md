# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This is a technical assignment (in Latvian). The repo holds the spec (`Tehniskais uzdevums_ Iekārtu datu apstrāde caur MQTT protokolu2.txt`), sample device payloads (`*_piemēri.json`), the dev infrastructure (`docker-compose.yml`, `broker/`) and the initial DB schema (`db/migrations/001_init.sql`). No Python code exists yet. There are no build, lint or test commands yet. Add them here once the project has them.

## Commands

- `cp .env.example .env && docker compose up -d --wait`: starts RabbitMQ (AMQP 5672, MQTT 1883, management UI http://localhost:15672) and Postgres 17 (5432). Credentials come from `.env` and default to `admin/admin` and `ingest/ingest` with database `telemetry`.
- SQL files in `db/migrations/` run automatically **only on first start** of an empty Postgres volume. To re-apply them, run `docker compose down -v`, which wipes all data. To apply a new file to a running DB: `docker compose exec -T postgres psql -U ingest -d telemetry -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/<file>.sql`.
- The `metrics` catalog is not seeded by SQL. It is meant to be synced from the Python `devices/` modules at service start, so a new device stays a single new module.
- `broker/rabbitmq.conf` is mounted as a `conf.d` drop-in. Anonymous MQTT is disabled, and MQTT publishes go to `amq.topic`.

## What is to be built

The pipeline: devices publish telemetry over MQTT, then Python 3.12 consumes it, validates data quality and stores it in PostgreSQL.

Required components and constraints from the spec:
- **RabbitMQ** with the MQTT plugin is the broker. Several clients (organizations or buildings) share one broker. Each client group needs its own authentication, its own data flow (separate vhosts and/or topic namespaces), and permissions that stop clients from reading each other's topics.
- **PostgreSQL** tables should match the logical structure of each device type. The spec stresses that every stored data point must say clearly what it represents (quantity, unit, meaning), so later visualization doesn't misread it.
- **Python consumer** subscribes to topics, parses each payload, validates it and writes it to the database. It must start automatically on server boot, using PM2 or an equivalent such as systemd.
- **Data quality criteria** must be written down explicitly: values within sane ranges, timestamps in chronological order with no overlaps, schema/format conformance, no duplicates or disallowed values.
- **Bonus:** consume through **AMQP** (durable queues bound to the MQTT topic exchange `amq.topic`) so messages pile up while the script is down. Also bonus: modular code, where adding a device type or data point means adding a parser or schema module rather than editing core logic.

## Sample payload formats

The sample files are **not valid JSON**. They are several JSON documents separated by `## ... ##` banner lines and comments. Split them before you load them as fixtures.

There are three distinct payload families, and each needs its own parser:

1. **Milesight / LoRaWAN (`Milesight_piemēri.json`)**: flat JSON keyed by `devEUI`, with an ISO-8601 UTC `time` (`...Z`). Device models are told apart by their field sets, not by an explicit type field:
   - AM103: environment sensor (`co2`, `temperature`, `humidity`, `battery`).
   - UC300: IO controller. Some keys carry a site prefix (`OstasSkati_*`) and some integer values look scaled (e.g. `hot_side: 2460`). `gpio_*` values are `"on"`/`"off"` strings.
   - Vicki: thermostatic radiator valve, with many boolean status/fault flags and `deviceName`.
   - Zenner SP12: water meter that reports every 3h. `volumes` is an array of `{hour, val}`, where `hour` is just the hour of day (11 means 11:00). The full timestamp has to be rebuilt from the message `time`, including the day rollover across midnight. `val` is a cumulative counter.
2. **Viltrus (`Viltrus_piemēri.json`)**: self-describing. `header.columns` maps numeric column IDs to `name`, `dataType` and `format`. `data[].f[id].v` holds the values, and each row has `ts`. Timestamps have **no timezone**. Device identity comes from `SN` and `name`. Parse by column ID through the header; don't hard-code names.
3. **WAGO-library PLCs (`Wago_piemēri.json`)**: `Lib_version`, `name`, `manufacturer`, `model`, `type` (e.g. `Electric meters`, `PLC`, `AHU`), and optional `serial`/`slave_id`. `DPS` is a list where each item holds **one** arbitrary data-point key plus `ts` and optional `reg_nr` (Modbus register). Timestamps use the IEC format `DT#YYYY-MM-DD-HH:MM:SS` with no timezone. Data-point names can contain spaces (`"max strava"`). For the Corrigo AHU, values look ×10-scaled (`Temp_SupplyAir: 201`), and `0` probably means "sensor not connected" rather than a real reading. Confirm this before you treat it as valid data.

Field names mix Latvian and English. Keep the original names as source identifiers, and map them to clear canonical metric names and units.

## Planned architecture

This plan has been agreed but not built yet. Update this section as the code lands.

### Layout

- `broker/`: RabbitMQ config: `enabled_plugins`, `rabbitmq.conf`, `definitions.json`, plus `add_tenant.sh` to provision a new client.
- `db/migrations/`: plain numbered SQL files (no ORM, no Alembic).
- `src/ingest/`: Python service, run as `python -m ingest`.
  - `consumer.py` and `pipeline.py` handle the flow raw → parse → validate → store.
  - `parsers/` has one module per **payload family**: `milesight`, `viltrus`, `wago`.
  - `devices/` has one module per **device model**. Each maps source field → canonical metric, unit, scale and valid range.
  - `validation/` holds the schema, range, timestamp and value checks.
  - `storage/` holds the repository code.
- `tests/fixtures/`: the sample payloads split into one valid JSON per file.
- `docs/data-model.md` and `docs/quality-criteria.md`: these document what each data point means and the validity rules, both required by the spec.
- `docker-compose.yml` runs RabbitMQ and Postgres for dev. `ecosystem.config.js` (PM2) and a systemd unit handle auto-start.

Parsers understand a wire format, and device modules define what fields *mean*. Keep the two separate: a new device on an existing format should only need a new `devices/` module.

### Broker and isolation

- **Isolation:** there is one vhost per client. Devices authenticate as `vhost:username`, and each user's permissions are limited to its own vhost. Topic permissions limit each gateway to its own building prefix. MQTT `/` maps to `.` in AMQP routing keys, so a rule reads `^ostas-skati\..*`.
- **Topic scheme:** `<building>/<format>/<device_id>`. The `<format>` segment picks the parser; don't guess the format from payload content.
- **Consumption:** the service consumes over **AMQP**, not MQTT. Each vhost has a durable queue `ingest` bound to `amq.topic` with key `#`, and the service holds one connection per vhost. Ack only after the database commit. Devices publish with QoS 1.
- **Libraries:** sync `pika` and `psycopg`.

### Database

- `tenants` and `buildings`: `buildings` carries a `timezone`, which is needed to interpret naive Viltrus/WAGO timestamps.
- `devices`, `metrics` and `measurements`:
  - `metrics` is the catalog of meaning: unit, description, `min_valid`/`max_valid`.
  - `measurements` is narrow: `(device_id, metric_id, ts)` primary key, `value_num`/`value_bool`/`value_text`, `quality`, `source_field`.
- `raw_messages`: every message is stored here first, as jsonb with a status and errors, for audit and reprocessing.
- Duplicates are dropped through the primary key with `INSERT ... ON CONFLICT DO NOTHING`.

### Validation policy

- **Reject:** unparseable or schema-invalid messages are marked `rejected` in `raw_messages`, then acked.
- **Store but flag:** implausible readings are stored with `quality = 'suspect'` and a reason. That covers out-of-range values, sentinel zeros, decreasing cumulative counters, and timestamps that are in the future or older than the last stored one. Never silently drop data.
- **Transient errors** (e.g. the database is down): don't ack, and reconnect with backoff.
