# Data model

How telemetry is stored, and what every stored data point means.

## Hierarchy and isolation

```
tenant (RabbitMQ vhost)  ─┬─ building (first MQTT topic segment, has a timezone)
                          │    └─ device (identified within its payload format)
                          │         └─ measurements (metric, channel, timestamp, value)
                          └─ raw_messages (every message as received)
```

MQTT topic: `<building>/<format>/<device_id>`, e.g. `ostas-skati/milesight/24e124725d021011`.
`<format>` selects the parser (`milesight`, `viltrus`, `wago`); `<device_id>` is the device's id
or name. A topic that names a different device than the payload is accepted but noted.

## Tables

| Table | Purpose |
|---|---|
| `tenants` | One per client organization. `vhost` is its RabbitMQ virtual host. |
| `buildings` | Belongs to a tenant. `slug` is the topic prefix. `timezone` interprets payload timestamps that have no offset (Viltrus, WAGO, Zenner hours). |
| `devices` | One per physical device, unique by building + format + `external_id`. `model` names the device module that interprets it; `metadata` keeps identity fields such as `slave_id` or `Lib_version`. |
| `metrics` | Catalog of meaning: quantity, unit, value type, kind and valid range of each data point. Synced from the device modules when the service starts. |
| `measurements` | One value per device + metric + channel + timestamp (primary key, so duplicates are impossible). |
| `raw_messages` | Each message exactly as received, with status `processed` / `rejected` and the reasons or warnings. Allows auditing and reprocessing. |
| `measurements_readable` | View joining all of the above, with local time, for visualization and ad hoc queries. |

### `measurements` columns

| Column | Meaning |
|---|---|
| `device_id`, `metric_id` | Which device, and what was measured (see `metrics`). |
| `channel` | Which of several identical inputs on one device: meter `Sk1`, probe `2`, alarm `Fire`. Empty if the device has only one. |
| `ts` | When the reading was taken, as UTC `timestamptz`. Not when it was received. |
| `value_num` / `value_bool` / `value_text` | The value, already scaled to the metric's unit. Exactly one is set, matching `metrics.value_type`. |
| `quality` | `good`, or `suspect` if a quality check failed (see [quality criteria](quality-criteria.md)). |
| `quality_reason` | Comma-separated reasons when suspect, e.g. `sensor_not_connected`. |
| `source_field` | The original field or column name in the payload, unchanged. |
| `raw_message_id` | The message this value came from. |

### Metric kinds

- **gauge**: an instantaneous value (temperature, power). Can go up and down.
- **counter**: a cumulative total (energy, water volume). Must never decrease; consumption over a period is the difference between two readings.
- **state**: a status, mode or flag. Booleans are on/off, alarm active, fault present. Numeric states are device enum codes and are not quantities, so they must not be averaged.

## Device mappings

Source field patterns: `<channel>` is the part stored in the `channel` column; `N` is a number.
Matching is case-insensitive where devices are inconsistent (Viltrus `Sk1` / `SK1`).
Values are stored as `raw ÷ scale`.

Fields marked *(unit assumed)* or *(scale unknown)* could not be confirmed from the samples
alone; see "Open questions" in the README.

<!-- generated:start -->

### Milesight AM103

Indoor air quality sensor. Format `milesight`, device type `environment_sensor`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `temperature` | `air_temperature` | °C | gauge |  | -20 … 60 | Indoor air temperature measured by the device |
| `humidity` | `relative_humidity` | % | gauge |  | 0 … 100 | Relative humidity of the air |
| `co2` | `co2` | ppm | gauge |  | 300 … 5000 | CO2 concentration in the air |
| `battery` | `battery_level` | % | gauge |  | 0 … 100 | Remaining battery charge |

### Milesight UC300

IoT controller: digital IO, PT100 probes, Modbus heat meter. Format `milesight`, device type `io_controller`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `gpio_in_<channel>` | `digital_input` |  | state |  |  | Digital input state (true = on/closed), channel = input number |
| `gpio_out_<channel>` | `digital_output` |  | state |  |  | Digital output state (true = on), channel = output number |
| `pt100_<channel>` | `probe_temperature` | °C | gauge |  | -50 … 200 | Temperature from a wired probe (e.g. PT100), channel = probe number |
| `adv_<channel>` | `analog_input` |  | gauge |  |  | Raw analog input value, unit depends on the connected sensor, channel = input |
| `<channel>_hot_side` | `heat_supply_temperature` | °C | gauge | ÷100 | 0 … 150 | Heat meter hot (supply) side water temperature, channel = meter |
| `<channel>_cold_side` | `heat_return_temperature` | °C | gauge | ÷100 | 0 … 150 | Heat meter cold (return) side water temperature, channel = meter |
| `<channel>_temp_diff` | `heat_temperature_difference` | K | gauge | ÷100 | -20 … 100 | Heat meter supply minus return temperature, channel = meter |
| `<channel>_current_flow` | `heat_flow_rate` | m³/h | gauge |  | 0 … 1000 | Heat meter water flow rate, channel = meter (unit assumed) |
| `<channel>_current_power` | `heat_power` | kW | gauge |  | 0 … 100000 | Heat meter thermal power, channel = meter (unit assumed) |
| `<channel>_energy` | `heat_energy` | kWh | counter |  | 0 …  | Heat meter cumulative thermal energy, channel = meter (unit assumed) |

### MClimate Vicki

Smart radiator thermostat. Format `milesight`, device type `radiator_valve`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `sensorTemperature` | `air_temperature` | °C | gauge |  | -20 … 60 | Indoor air temperature measured by the device |
| `relativeHumidity` | `relative_humidity` | % | gauge |  | 0 … 100 | Relative humidity of the air |
| `targetTemperature` | `target_temperature` | °C | gauge |  | 5 … 30 | Temperature setpoint |
| `openProcentage` | `valve_opening` | % | gauge |  | 0 … 100 | Valve opening (0 = closed, 100 = fully open) |
| `motorPosition` | `motor_position` | steps | gauge |  | 0 … 1000 | Valve motor position in motor steps |
| `motorRange` | `motor_range` | steps | gauge |  | 0 … 1000 | Calibrated full motor travel in steps |
| `batteryVoltage` | `battery_voltage` | V | gauge |  | 1.5 … 4 | Battery voltage |
| `openWindow` | `open_window_detected` |  | state |  |  | Open window detected |
| `childLock` | `child_lock` |  | state |  |  | Child lock enabled |
| `attachedBackplate` | `backplate_attached` |  | state |  |  | Device mounted on its backplate |
| `perceiveAsOnline` | `online` |  | state |  |  | Device considers itself online |
| `brokenSensor` | `fault_broken_sensor` |  | state |  |  | Fault: temperature sensor broken |
| `calibrationFailed` | `fault_calibration` |  | state |  |  | Fault: valve calibration failed |
| `highMotorConsumption` | `fault_high_motor_current` |  | state |  |  | Fault: motor current too high |
| `lowMotorConsumption` | `fault_low_motor_current` |  | state |  |  | Fault: motor current too low |

Not stored as measurements: `newVersion`

### Zenner ZennerSP12

Water meter. Format `milesight`, device type `water_meter`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `volumes` | `water_volume` | m³ | counter | ÷1000 | 0 …  | Cumulative water meter reading |
| `ok` | `device_ok` |  | state |  |  | Device reports no errors |

### Viltrus Viltrus

Data logger reading electricity meters. Format `viltrus`, device type `energy_logger`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `<channel>_aktiva_jauda` | `active_power` | kW | gauge |  | -10000 … 10000 | Active power, channel = meter |
| `<channel>_kopeja_jauda` | `apparent_power` | kVA | gauge |  | 0 … 10000 | Apparent (total) power, channel = meter |
| `<channel>_aktivas_en_paterins` | `active_energy_import` | kWh | counter |  | 0 …  | Cumulative active energy consumed (imported), channel = meter |
| `<channel>_reaktivas_en_paterins` | `reactive_energy_import` | kvarh | counter |  | 0 …  | Cumulative reactive energy consumed, channel = meter |
| `<channel>_imports` | `active_energy_import` | kWh | counter | ÷1000 | 0 …  | Cumulative active energy consumed (imported), channel = meter |
| `<channel>_eksports` | `active_energy_export` | kWh | counter | ÷1000 | 0 …  | Cumulative active energy exported (fed back), channel = meter |
| `<channel>_frekvence` | `grid_frequency` | Hz | gauge | ÷100 | 45 … 55 | Mains frequency |

### WAGO 751-9301

PLC controller for transformer substation monitoring. Format `wago`, device type `plc`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `<channel>_temp` | `transformer_temperature` | °C | gauge |  | -40 … 150 | Transformer temperature, channel = transformer |
| `Alarm_<channel>` | `alarm` |  | state |  |  | Alarm active (true) or clear (false), channel = alarm name |
| `max strava` | `max_current` | A | gauge |  | 0 … 10000 | Maximum current ('max strava') measured by the PLC (unit assumed) |

### Corrigo E_G3

Air handling unit controller. Format `wago`, device type `ahu`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `UnitRunMode` | `ahu_unit_run_mode` |  | state |  |  | Unit run mode (Corrigo enum) |
| `RunMode` | `ahu_run_mode` |  | state |  |  | Run mode (Corrigo enum) |
| `Control_Mode` | `ahu_control_mode` |  | state |  |  | Temperature control mode (Corrigo enum) |
| `Temp_SupplyAir` | `supply_air_temperature` | °C | gauge | ÷10, raw 0 = no reading | -40 … 80 | Supply air temperature |
| `Temp_ExtractAir` | `extract_air_temperature` | °C | gauge | ÷10, raw 0 = no reading | -40 … 80 | Extract air temperature |
| `Temp_Room<channel>` | `room_temperature` | °C | gauge | ÷10, raw 0 = no reading | -40 … 80 | Room temperature, channel = room sensor |
| `CO2_Level` | `co2` | ppm | gauge | raw 0 = no reading | 300 … 5000 | CO2 concentration in the air |
| `Humidity_Duct` | `duct_relative_humidity` | % | gauge | ÷10, raw 0 = no reading | 0 … 100 | Relative humidity in the air duct |
| `Humidity_Room` | `relative_humidity` | % | gauge | ÷10, raw 0 = no reading | 0 … 100 | Relative humidity of the air |
| `Setpoint_SupplyAirTemp` | `supply_air_temperature_setpoint` | °C | gauge | ÷10 | 5 … 40 | Supply air temperature setpoint |
| `Setpoint_Humidity` | `humidity_setpoint` | % | gauge | ÷10 | 0 … 100 | Relative humidity setpoint |
| `Setpoint_CO2` | `co2_setpoint` |  | gauge |  |  | CO2 setpoint (raw register, scale unknown) |
| `Setpoint_<channel>eco` | `fan_speed_setpoint_eco` | % | gauge | ÷10 | 0 … 100 | Fan speed setpoint in economy mode, channel = Supp (supply) / Exh (exhaust) |
| `Setpoint_<channel>Normal` | `fan_speed_setpoint_normal` | % | gauge | ÷10 | 0 … 100 | Fan speed setpoint in normal mode, channel = Supp (supply) / Exh (exhaust) |
| `Alarm_AckById` | `ahu_alarm_ack_by` |  | state |  |  | Id of the last alarm acknowledged (255 = none) |
| `Alarm_<channel>` | `alarm` |  | state |  |  | Alarm active (true) or clear (false), channel = alarm name |

### Schneider iEM3250

Three-phase electricity meter. Format `wago`, device type `electric_meter`.

| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |
|---|---|---|---|---|---|---|
| `Curr_avg` | `current_avg` | A | gauge |  | 0 … 63 | Average phase current |
| `Curr_fr` | `grid_frequency` | Hz | gauge |  | 45 … 55 | Mains frequency |
| `TAP` | `active_power` | kW | gauge |  | -10000 … 10000 | Active power, channel = meter |
| `TEI` | `active_energy_import` | kWh | counter |  | 0 …  | Cumulative active energy consumed (imported), channel = meter |
| `LL_avg` | `voltage_ll_avg` | V | gauge |  | 300 … 500 | Average line-to-line voltage |

Not stored as measurements: `SN`

<!-- generated:end -->
