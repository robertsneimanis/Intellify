-- 001_init: core schema for telemetry ingestion.
--
-- Hierarchy: tenant (= RabbitMQ vhost) -> building (= topic prefix) -> device.
-- Each reading is one row in `measurements`, linked to a `metrics` entry that
-- says what the number means (quantity, unit, valid range). The metric catalog
-- is synced from the Python `devices/` modules at service start, not seeded here.

BEGIN;

CREATE TABLE schema_migrations (
    version    text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- True if `tz` is a timezone name Postgres understands (e.g. 'Europe/Riga').
CREATE FUNCTION is_valid_timezone(tz text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    PERFORM now() AT TIME ZONE tz;
    RETURN true;
EXCEPTION WHEN invalid_parameter_value THEN
    RETURN false;
END;
$$;

CREATE TABLE tenants (
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vhost      text NOT NULL UNIQUE,           -- RabbitMQ vhost, e.g. 'acme'
    name       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE buildings (
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id  integer NOT NULL REFERENCES tenants (id),
    slug       text NOT NULL,                  -- first topic segment, e.g. 'ostas-skati'
    name       text NOT NULL,
    -- Used to interpret payload timestamps that carry no offset (Viltrus, WAGO).
    timezone   text NOT NULL DEFAULT 'Europe/Riga' CHECK (is_valid_timezone(timezone)),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, slug)
);

CREATE TABLE devices (
    id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    building_id   integer NOT NULL REFERENCES buildings (id),
    source_format text NOT NULL CHECK (source_format IN ('milesight', 'viltrus', 'wago')),
    -- Identity within the format: devEUI (Milesight), SN (Viltrus),
    -- serial or name/slave_id (WAGO).
    external_id   text NOT NULL,
    model         text NOT NULL,               -- devices/ module key, e.g. 'AM103', 'iEM3250'
    manufacturer  text,
    device_type   text NOT NULL,               -- e.g. 'environment_sensor', 'water_meter', 'ahu'
    name          text,                        -- human name from payload, if any
    metadata      jsonb NOT NULL DEFAULT '{}', -- extra identity fields (Lib_version, slave_id, ...)
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (building_id, source_format, external_id)
);

-- Catalog of meaning: one row per canonical metric.
CREATE TABLE metrics (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         text NOT NULL UNIQUE,          -- canonical name, e.g. 'supply_air_temperature'
    quantity    text NOT NULL,                 -- physical quantity, e.g. 'temperature', 'energy'
    unit        text,                          -- SI-style unit after scaling, e.g. '°C', 'kWh'; NULL for states
    value_type  text NOT NULL CHECK (value_type IN ('numeric', 'boolean', 'text')),
    -- gauge: instantaneous; counter: cumulative, must not decrease;
    -- state: enumerated/on-off status or mode.
    kind        text NOT NULL CHECK (kind IN ('gauge', 'counter', 'state')),
    description text NOT NULL,
    min_valid   double precision,
    max_valid   double precision,
    CHECK (min_valid IS NULL OR max_valid IS NULL OR min_valid <= max_valid),
    CHECK (value_type = 'numeric' OR (min_valid IS NULL AND max_valid IS NULL))
);

-- Every incoming message, stored before parsing, for audit and reprocessing.
CREATE TABLE raw_messages (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vhost         text NOT NULL,
    routing_key   text NOT NULL,               -- AMQP form of the MQTT topic: building.format.device
    received_at   timestamptz NOT NULL DEFAULT now(),
    payload       jsonb,                       -- set when the body is valid JSON
    payload_text  text,                        -- set when it is not, so nothing is lost
    status        text NOT NULL DEFAULT 'received'
                  CHECK (status IN ('received', 'processed', 'rejected')),
    errors        jsonb NOT NULL DEFAULT '[]', -- rejection reasons and per-field warnings
    processed_at  timestamptz,
    CHECK (num_nonnulls(payload, payload_text) = 1)
);

CREATE INDEX raw_messages_status_idx ON raw_messages (status, received_at);

-- Narrow measurement table: one value per (device, metric, timestamp).
-- The primary key drops duplicates (INSERT ... ON CONFLICT DO NOTHING) and
-- serves "latest value" lookups for chronology and counter checks.
CREATE TABLE measurements (
    device_id      integer NOT NULL REFERENCES devices (id),
    metric_id      integer NOT NULL REFERENCES metrics (id),
    ts             timestamptz NOT NULL,       -- when the reading was taken (UTC)
    value_num      double precision,           -- already scaled to metrics.unit
    value_bool     boolean,
    value_text     text,
    quality        text NOT NULL DEFAULT 'good' CHECK (quality IN ('good', 'suspect')),
    quality_reason text,                       -- why it is suspect, e.g. 'out_of_range'
    source_field   text NOT NULL,              -- original payload key / column name
    raw_message_id bigint NOT NULL REFERENCES raw_messages (id),
    PRIMARY KEY (device_id, metric_id, ts),
    CHECK (num_nonnulls(value_num, value_bool, value_text) = 1),
    CHECK ((quality = 'suspect') = (quality_reason IS NOT NULL))
);

CREATE INDEX measurements_metric_ts_idx ON measurements (metric_id, ts);

-- Readable view for visualization and ad-hoc queries.
CREATE VIEW measurements_readable AS
SELECT t.vhost        AS tenant,
       b.slug         AS building,
       d.name         AS device_name,
       d.model,
       d.device_type,
       m.key          AS metric,
       m.description,
       m.unit,
       me.ts,
       me.ts AT TIME ZONE b.timezone AS ts_local,
       me.value_num,
       me.value_bool,
       me.value_text,
       me.quality,
       me.quality_reason,
       me.source_field
FROM measurements me
JOIN devices   d ON d.id = me.device_id
JOIN buildings b ON b.id = d.building_id
JOIN tenants   t ON t.id = b.tenant_id
JOIN metrics   m ON m.id = me.metric_id;

INSERT INTO schema_migrations (version) VALUES ('001_init');

COMMIT;
