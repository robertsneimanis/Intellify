"""Milesight AM103: indoor CO2, temperature and humidity sensor (LoRaWAN)."""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field

MODEL = DeviceModel(
    source_format="milesight",
    model="AM103",
    device_type="environment_sensor",
    manufacturer="Milesight",
    description="Indoor air quality sensor",
    detect=frozenset({"co2", "temperature", "humidity"}),
    fields=(
        Field("temperature", m.AIR_TEMPERATURE),
        Field("humidity", m.RELATIVE_HUMIDITY),
        Field("co2", m.CO2),
        Field("battery", m.BATTERY_LEVEL),
    ),
)
