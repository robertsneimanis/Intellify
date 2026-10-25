"""Milesight UC300: IoT controller with digital IO, PT100 inputs and a Modbus heat meter.

The `<site>_*` fields come from a heat meter read over Modbus; the prefix
(e.g. `OstasSkati`) names the meter and becomes the channel. Temperatures are
sent in hundredths of a degree (`hot_side: 2460` = 24.60 °C); this matches
`temp_diff = hot_side - cold_side` in the samples.
"""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric

SUPPLY_TEMPERATURE = Metric(
    "heat_supply_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Heat meter hot (supply) side water temperature, channel = meter",
    0,
    150,
)
RETURN_TEMPERATURE = Metric(
    "heat_return_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Heat meter cold (return) side water temperature, channel = meter",
    0,
    150,
)
TEMPERATURE_DIFFERENCE = Metric(
    "heat_temperature_difference",
    "temperature_difference",
    "K",
    "numeric",
    "gauge",
    "Heat meter supply minus return temperature, channel = meter",
    -20,
    100,
)
HEAT_FLOW = Metric(
    "heat_flow_rate",
    "volume_flow",
    "m³/h",
    "numeric",
    "gauge",
    "Heat meter water flow rate, channel = meter (unit assumed)",
    0,
    1000,
)
HEAT_POWER = Metric(
    "heat_power",
    "power",
    "kW",
    "numeric",
    "gauge",
    "Heat meter thermal power, channel = meter (unit assumed)",
    0,
    100000,
)
HEAT_ENERGY = Metric(
    "heat_energy",
    "energy",
    "kWh",
    "numeric",
    "counter",
    "Heat meter cumulative thermal energy, channel = meter (unit assumed)",
    0,
    None,
)
ANALOG_INPUT = Metric(
    "analog_input",
    "analog",
    None,
    "numeric",
    "gauge",
    "Raw analog input value, unit depends on the connected sensor, channel = input",
)

METER = r"(?P<channel>\w+?)_"

MODEL = DeviceModel(
    source_format="milesight",
    model="UC300",
    device_type="io_controller",
    manufacturer="Milesight",
    description="IoT controller: digital IO, PT100 probes, Modbus heat meter",
    detect=frozenset({"gpio_in_1", "gpio_out_1"}),
    fields=(
        Field(r"gpio_in_(?P<channel>\d+)", m.DIGITAL_INPUT),
        Field(r"gpio_out_(?P<channel>\d+)", m.DIGITAL_OUTPUT),
        Field(r"pt100_(?P<channel>\d+)", m.PROBE_TEMPERATURE),
        Field(r"adv_(?P<channel>\d+)", ANALOG_INPUT),
        Field(METER + "hot_side", SUPPLY_TEMPERATURE, divisor=100),
        Field(METER + "cold_side", RETURN_TEMPERATURE, divisor=100),
        Field(METER + "temp_diff", TEMPERATURE_DIFFERENCE, divisor=100),
        Field(METER + "current_flow", HEAT_FLOW),
        Field(METER + "current_power", HEAT_POWER),
        Field(METER + "energy", HEAT_ENERGY),
    ),
)
