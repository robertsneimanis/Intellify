"""Metrics shared by several device models.

Model-specific metrics live in the device module itself. A metric key must
mean the same thing everywhere it is used; the registry refuses two different
definitions under one key.
"""

from ingest.devices.base import Metric

AIR_TEMPERATURE = Metric(
    "air_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Indoor air temperature measured by the device",
    -20,
    60,
)
RELATIVE_HUMIDITY = Metric(
    "relative_humidity",
    "relative_humidity",
    "%",
    "numeric",
    "gauge",
    "Relative humidity of the air",
    0,
    100,
)
CO2 = Metric(
    "co2",
    "concentration",
    "ppm",
    "numeric",
    "gauge",
    "CO2 concentration in the air",
    300,
    5000,
)
BATTERY_LEVEL = Metric(
    "battery_level",
    "battery",
    "%",
    "numeric",
    "gauge",
    "Remaining battery charge",
    0,
    100,
)
BATTERY_VOLTAGE = Metric(
    "battery_voltage",
    "voltage",
    "V",
    "numeric",
    "gauge",
    "Battery voltage",
    1.5,
    4.0,
)
PROBE_TEMPERATURE = Metric(
    "probe_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Temperature from a wired probe (e.g. PT100), channel = probe number",
    -50,
    200,
)
DIGITAL_INPUT = Metric(
    "digital_input",
    "state",
    None,
    "boolean",
    "state",
    "Digital input state (true = on/closed), channel = input number",
)
DIGITAL_OUTPUT = Metric(
    "digital_output",
    "state",
    None,
    "boolean",
    "state",
    "Digital output state (true = on), channel = output number",
)
ALARM = Metric(
    "alarm",
    "state",
    None,
    "boolean",
    "state",
    "Alarm active (true) or clear (false), channel = alarm name",
)
ACTIVE_POWER = Metric(
    "active_power",
    "power",
    "kW",
    "numeric",
    "gauge",
    "Active power, channel = meter",
    -10000,
    10000,
)
ACTIVE_ENERGY_IMPORT = Metric(
    "active_energy_import",
    "energy",
    "kWh",
    "numeric",
    "counter",
    "Cumulative active energy consumed (imported), channel = meter",
    0,
    None,
)
ACTIVE_ENERGY_EXPORT = Metric(
    "active_energy_export",
    "energy",
    "kWh",
    "numeric",
    "counter",
    "Cumulative active energy exported (fed back), channel = meter",
    0,
    None,
)
GRID_FREQUENCY = Metric(
    "grid_frequency",
    "frequency",
    "Hz",
    "numeric",
    "gauge",
    "Mains frequency",
    45,
    55,
)
