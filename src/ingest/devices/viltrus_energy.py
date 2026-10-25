"""Viltrus data logger with electricity meters.

Viltrus columns are configured per installation, so fields are matched by
name pattern, and the meter prefix (`Sk1`, `61`, ...) becomes the channel.
Matching ignores case (`Sk1_` and `SK1_` both occur).

- `SkN_*` meters report kW / kVA / kWh / kvarh as floats.
- `NN_imports` / `NN_eksports` are integer counters, assumed to be Wh, stored in kWh.
- `NN_frekvence` is in hundredths of a hertz (5001 = 50.01 Hz).
"""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric

APPARENT_POWER = Metric(
    "apparent_power",
    "power",
    "kVA",
    "numeric",
    "gauge",
    "Apparent (total) power, channel = meter",
    0,
    10000,
)
REACTIVE_ENERGY_IMPORT = Metric(
    "reactive_energy_import",
    "energy",
    "kvarh",
    "numeric",
    "counter",
    "Cumulative reactive energy consumed, channel = meter",
    0,
    None,
)

SK = r"(?i:(?P<channel>sk\d+))_"
NN = r"(?P<channel>\d+)_"

MODEL = DeviceModel(
    source_format="viltrus",
    model="Viltrus",
    device_type="energy_logger",
    manufacturer="Viltrus",
    description="Data logger reading electricity meters",
    detect=frozenset(),  # the only Viltrus model so far: matches every Viltrus payload
    fields=(
        Field(SK + "(?i:aktiva_jauda)", m.ACTIVE_POWER),
        Field(SK + "(?i:kopeja_jauda)", APPARENT_POWER),
        Field(SK + "(?i:aktivas_en_paterins)", m.ACTIVE_ENERGY_IMPORT),
        Field(SK + "(?i:reaktivas_en_paterins)", REACTIVE_ENERGY_IMPORT),
        Field(NN + "imports", m.ACTIVE_ENERGY_IMPORT, divisor=1000),
        Field(NN + "eksports", m.ACTIVE_ENERGY_EXPORT, divisor=1000),
        Field(NN + "frekvence", m.GRID_FREQUENCY, divisor=100),
    ),
)
