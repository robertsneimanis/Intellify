"""Zenner SP12 water meter via LoRaWAN, reporting hourly readings every 3 hours.

`volumes[].val` is the cumulative meter reading. It is assumed to be in
litres (hourly steps of ~150-180 in the samples) and stored in m³.
"""

from ingest.devices.base import DeviceModel, Field, Metric

WATER_VOLUME = Metric(
    "water_volume",
    "volume",
    "m³",
    "numeric",
    "counter",
    "Cumulative water meter reading",
    0,
    None,
)
DEVICE_OK = Metric(
    "device_ok",
    "state",
    None,
    "boolean",
    "state",
    "Device reports no errors",
)

MODEL = DeviceModel(
    source_format="milesight",
    model="ZennerSP12",
    device_type="water_meter",
    manufacturer="Zenner",
    description="Water meter",
    fields=(
        Field("volumes", WATER_VOLUME, divisor=1000),
        Field("ok", DEVICE_OK),
    ),
)
