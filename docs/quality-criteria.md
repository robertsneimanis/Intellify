# Data quality criteria

When incoming data counts as valid, and what happens when it isn't.

The guiding rule: **nothing is silently dropped.** Every message is first stored in
`raw_messages`. A problem then has one of four outcomes, depending on how much of the data
can still be trusted.

| Outcome | Applies to | Where it's recorded |
|---|---|---|
| **Reject message** | The message as a whole cannot be interpreted. | `raw_messages.status = 'rejected'`, reason in `errors`. No measurements stored. |
| **Skip field** | One field can't be interpreted, but the rest of the message can. | Field left out, warning in `raw_messages.errors`. The raw value stays in `raw_messages.payload`. |
| **Store as suspect** | The value is well-formed but implausible. | Stored with `quality = 'suspect'` and `quality_reason`. |
| **Drop duplicate** | Exactly this reading is already stored. | Not stored again (primary key), counted in `raw_messages.errors`. |

Charts and automations should use `quality = 'good'` by default and show suspect values only
when someone explicitly asks for them.

## 1. Schema and format: reject the message

Checked by the parser for each payload format (`src/ingest/parsers/`).

| Criterion | Example rejection |
|---|---|
| Body is UTF-8 JSON and an object | `body is not valid UTF-8 JSON` |
| Topic is `<building>/<format>/<device_id>` | `topic 'x.y' is not <building>/<format>/<device_id>` |
| Building exists in the tenant's vhost | `unknown building 'b' for tenant 'demo'` |
| Format is a known parser | `unknown format 'modbus'` |
| Required identity and time fields are present and correctly typed (Milesight `devEUI`/`time`; Viltrus `SN`/`header.columns`/`data`; WAGO `name`/`model`/`type`/`DPS`) | `missing field 'model'` |
| Timestamps parse in the format's convention: ISO-8601 with offset (Milesight), ISO-8601 without offset (Viltrus), IEC `DT#YYYY-MM-DD-HH:MM:SS` (WAGO) | `invalid IEC timestamp '2025-06-30 12:26'` |
| Values are scalars, apart from known structures such as Zenner `volumes: [{hour, val}]` with `hour` 0–23 | `field 'x' has unsupported type dict` |
| Viltrus: every value's column ID is described in `header.columns`; `NUMBER` columns hold numbers | `value for column '9' not described in header` |
| WAGO: each `DPS` item holds exactly one data point, and `reg_nr` is an integer | `DPS item must hold exactly one data point` |
| A device module exists for the payload (by `model`, or by its field set for Milesight) | `cannot identify milesight device model` |

## 2. Field-level: skip the field, keep the message

| Criterion | Warning |
|---|---|
| The device module maps the field to a metric | `foo: no mapping in AM103, not stored` |
| The value converts to the metric's type: numbers for numeric metrics; `true/false`, `0/1` or `on/off` for boolean ones | `ok: expected an on/off value, got 'maybe', not stored` |
| The value is not `null` | `co2: null value skipped` |

Fields a device module lists under `ignore` (identity fields such as the meter `SN`) are left
out without a warning.

## 3. Plausibility: store as suspect

Checked in `src/ingest/validation.py` and, for sentinels, by the device mapping.

| Reason code | Criterion |
|---|---|
| `out_of_range` | The value is outside the metric's `min_valid`…`max_valid` in `metrics`. Each range comes from the physical limits of the quantity or sensor, e.g. CO₂ 300–5000 ppm, relative humidity 0–100 %, mains frequency 45–55 Hz, Vicki setpoint 5–30 °C. |
| `sensor_not_connected` | The device sent the value it uses for "no sensor". For the Corrigo AHU, that is a raw `0` on temperature, humidity and CO₂ inputs. |
| `future_timestamp` | The reading is more than 5 minutes ahead of the server clock. |
| `implausible_timestamp` | The reading is before 2015-01-01, which usually means a device clock that was never set or has reset. |
| `out_of_order` | The reading is older than the newest value already stored for the same device, metric and channel. Timestamps must arrive in chronological order. |
| `counter_decreased` | A counter (energy, volume) is lower than the previous reading in time. This means a meter replacement, a rollover or bad data. |

Chronology and counter checks compare against both the database and the earlier readings in
the same message, which are processed in time order.

## 4. Duplicates: drop

- **Same device, metric, channel and timestamp:** this is a duplicate by definition. It is
  enforced by the `measurements` primary key with `ON CONFLICT DO NOTHING`. This makes
  redelivery safe: if the service crashes after the database commit but before the broker
  acknowledgement, reprocessing the message changes nothing.
- **A message that contains the same series and timestamp twice:** the first value is kept.
  If the second value differs, a warning records both values.

## Timezones

Every timestamp is stored as an absolute instant (`timestamptz`).

- Milesight `time` carries an explicit UTC offset and is used as is.
- Viltrus `ts` and WAGO `DT#…` timestamps carry no offset. They are read in the building's
  `timezone`.
- Zenner `volumes[].hour` is the hour of day in the building's local time, on or before the
  message time. For example, a message sent at 09:19Z (12:19 in Riga) reports hours 10–12.
  When an hour falls after the message time, it belongs to the previous day.

## Transient failures

If the database or broker is unavailable, nothing is acknowledged. The message stays in the
durable queue, and the service reconnects with exponential backoff (1 s up to 60 s). This is
not a data quality outcome, because no data is judged or lost.
