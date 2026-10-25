"""WAGO 751-9301 PLC monitoring transformer substations (TP).

PLC data points are project-specific; these patterns cover the points seen
in the samples. `TPn_temp` is a transformer temperature, `Alarm_*` are
0/1 alarm flags.
"""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric

TRANSFORMER_TEMPERATURE = Metric(
    "transformer_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Transformer temperature, channel = transformer",
    -40,
    150,
)
MAX_CURRENT = Metric(
    "max_current",
    "current",
    "A",
    "numeric",
    "gauge",
    "Maximum current ('max strava') measured by the PLC (unit assumed)",
    0,
    10000,
)

MODEL = DeviceModel(
    source_format="wago",
    model="751-9301",
    device_type="plc",
    manufacturer="WAGO",
    description="PLC controller for transformer substation monitoring",
    fields=(
        Field(r"(?P<channel>TP\d+)_temp", TRANSFORMER_TEMPERATURE),
        Field(r"Alarm_(?P<channel>\w+)", m.ALARM),
        Field("max strava", MAX_CURRENT),
    ),
)
