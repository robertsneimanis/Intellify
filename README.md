# Intellify telemetry ingestion

Devices publish telemetry over MQTT to RabbitMQ. A Python 3.12 service consumes it over AMQP,
checks data quality and stores it in PostgreSQL, so that each value carries its meaning, unit
and quality. The assignment is in
[`Tehniskais uzdevums_ Iekārtu datu apstrāde caur MQTT protokolu2.txt`](Tehniskais%20uzdevums_%20Iekārtu%20datu%20apstrāde%20caur%20MQTT%20protokolu2.txt).

```
 devices / gateways                RabbitMQ                          ingest service               PostgreSQL
┌──────────────────┐  MQTT   ┌─────────────────────────┐  AMQP   ┌────────────────────────┐   ┌──────────────┐
│ ostas-skati/     │ ──────► │ vhost per tenant        │ ──────► │ parse   (per format)   │   │ raw_messages │
│  milesight/<id>  │  QoS 1  │  amq.topic ──► "ingest" │  ack    │ map     (per device)   │──►│ devices      │
│  wago/<name> ... │         │  durable queue, key "#" │  after  │ validate (quality)     │   │ measurements │
└──────────────────┘         └─────────────────────────┘  commit └────────────────────────┘   │ metrics      │
                                                                                             └──────────────┘
```

## How the requirements are met

| Requirement | Solution |
|---|---|
| RabbitMQ with MQTT | The `rabbitmq_mqtt` plugin ([`broker/`](broker)). Anonymous access is off, and MQTT publishes go to `amq.topic`. |
| Separating clients and buildings | One **vhost per tenant**, one **MQTT user per building**. See [Isolation](#isolation). |
| Data structure per device type | [`docs/data-model.md`](docs/data-model.md) documents every stored data point: metric, unit, scale, valid range and meaning. It is generated from the device modules, so it can't drift from the code. |
| PostgreSQL tables | [`db/migrations/001_init.sql`](db/migrations/001_init.sql) |
| Receive, check, store | `python -m ingest`: [`src/ingest/`](src/ingest) |
| Data quality criteria | [`docs/quality-criteria.md`](docs/quality-criteria.md) |
| Auto start on boot | PM2 ([`ecosystem.config.js`](ecosystem.config.js)) or systemd ([`deploy/`](deploy)). The containers use `restart: unless-stopped`. |
| Bonus: AMQP with queueing | The service consumes a durable queue over AMQP and acknowledges only after the database commit. Messages pile up while the service is down. |
| Bonus: modular | New device on a known format: add one module in `src/ingest/devices/`. New format: add one parser in `src/ingest/parsers/`. The core code doesn't change. |

## Quick start

Requires Docker and Python 3.12.

```sh
cp .env.example .env
docker compose up -d --wait                      # RabbitMQ (MQTT 1883, AMQP 5672, UI :15672) + Postgres

python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'

# Provision the service user, one tenant and one building
.venv/bin/python -m ingest.admin init
.venv/bin/python -m ingest.admin add-tenant demo "Demo Ltd"
.venv/bin/python -m ingest.admin add-building demo ostas-skati "Ostas Skati" --password demo-secret

# Publish the sample payloads over MQTT, then start the service to consume them
.venv/bin/python scripts/publish_samples.py --username demo:demo-ostas-skati \
    --password demo-secret --building ostas-skati
.venv/bin/python -m ingest
```

Then look at the result:

```sh
docker compose exec postgres psql -U ingest -d telemetry -c \
  "SELECT device_type, metric, channel, value_num, value_bool, unit, quality, quality_reason, ts_local
   FROM measurements_readable ORDER BY ts LIMIT 20"
```

To run in production, use `pm2 start ecosystem.config.js && pm2 save && pm2 startup`, or
install the systemd unit in `deploy/`.

## Isolation

`python -m ingest.admin` applies this model through the RabbitMQ management API:

- **Tenant = vhost.** Users exist per vhost, and a tenant's users have no permissions in any
  other vhost.
- **Building = MQTT user `<vhost>-<building>`.** Devices log in as
  `<vhost>:<vhost>-<building>`; the part before the colon selects the vhost. The user may only
  *publish*: it has no read permission and can't create queues. Its topic permissions allow
  writing only to `<building>/…`.
- **The ingest service user** may only use the `ingest` queue in each tenant vhost.

These cases were checked against the running broker:

| Attempt | Result |
|---|---|
| Building user publishes to its own `ostas-skati/...` | accepted |
| Building user publishes to `other-building/...` in the same vhost | refused: topic write access |
| Building user logs in to another tenant's vhost | refused: no vhost access |
| Building user subscribes to `#` | refused: not authorized |
| Wrong password, or login without a vhost prefix | refused |

## Processing

Each message is handled in one database transaction (`src/ingest/pipeline.py`):

1. Store the body in `raw_messages`.
2. Read `<building>/<format>/<device_id>` from the topic. The `<format>` part selects the
   **parser** (`milesight`, `viltrus`, `wago`), which checks the schema and returns raw
   readings with timezone-aware timestamps.
3. The **device module** for the model gives each field its meaning: it maps the field to a
   canonical metric, applies scaling, and recognises sentinel values such as "sensor not
   connected".
4. **Validation** flags implausible values as `suspect`: out of range, future or old
   timestamps, decreasing counters.
5. Insert the measurements, skipping duplicates. Mark the raw message `processed` or
   `rejected`.
6. Commit, then acknowledge the message to RabbitMQ.

An unusable message is stored as `rejected` with its reasons, and is acknowledged so it
doesn't block the queue. A database or broker outage acknowledges nothing; the service
reconnects with backoff. The service starts one consumer per tenant vhost and picks up new
tenants without a restart.

## Adding a device type

Create `src/ingest/devices/<model>.py` with a module-level `MODEL = DeviceModel(...)` that lists
`Field(pattern, metric, divisor=..., sentinels=...)` entries. Reuse metrics from
`devices/metrics.py` where the meaning is the same. Then run `python -m ingest.docgen` to update
the data model documentation. Modules are discovered automatically, and the metric catalog is
synced to the database when the service starts.

## Development

```sh
.venv/bin/pytest            # unit tests, plus integration tests if Postgres is running
.venv/bin/ruff check . && .venv/bin/ruff format --check .
python scripts/split_samples.py   # regenerate tests/fixtures from the *_piemēri.json samples
python -m ingest.docgen           # regenerate the device tables in docs/data-model.md
```

The integration tests create and use a separate `telemetry_test` database.

## Assumptions

The samples and the available device information don't settle these points. They are
deliberate, documented decisions, marked *(unit assumed)* or *(scale unknown)* in
[`docs/data-model.md`](docs/data-model.md). If one turns out wrong, the fix is a change to the
`divisor` or unit in one device module, followed by `python -m ingest.docgen`. Raw payloads are
kept in `raw_messages`, so stored values can be recomputed.

1. **UC300 heat meter** (`OstasSkati_*`): temperatures are ÷100. This is consistent with
   `temp_diff = hot_side − cold_side`. The units of `energy` (assumed kWh), `current_flow`
   (m³/h) and `current_power` (kW) are assumed, and their scale is unknown because they are
   0 or have no reference value in the sample.
2. **Zenner SP12** `val`: assumed to be litres and stored as m³.
3. **Viltrus** `NN_imports` / `NN_eksports`: assumed to be Wh and stored as kWh.
   `NN_frekvence` is assumed to be ÷100 Hz.
4. **Corrigo AHU:** analog values are assumed ×10, and a raw `0` on sensor inputs is taken to
   mean "not connected". `Setpoint_CO2 = 3` doesn't fit ppm, so it is stored raw. Fan
   setpoints are assumed to be % ×10. `RunMode` and the other enum codes are stored as numeric
   states, not translated into names.
5. **WAGO PLC** `max strava`: assumed to be the maximum current in A.
