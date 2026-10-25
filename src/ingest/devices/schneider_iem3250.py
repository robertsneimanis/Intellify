"""Schneider iEM3250 three-phase energy meter, read over Modbus by a WAGO PLC."""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric

CURRENT_AVG = Metric(
    "current_avg",
    "current",
    "A",
    "numeric",
    "gauge",
    "Average phase current",
    0,
    63,  # iEM3250 is a direct-connect meter, max 63 A
)
VOLTAGE_LL_AVG = Metric(
    "voltage_ll_avg",
    "voltage",
    "V",
    "numeric",
    "gauge",
    "Average line-to-line voltage",
    300,
    500,
)

MODEL = DeviceModel(
    source_format="wago",
    model="iEM3250",
    device_type="electric_meter",
    manufacturer="Schneider",
    description="Three-phase electricity meter",
    ignore=frozenset({"SN"}),  # meter serial number, identity not measurement
    fields=(
        Field("Curr_avg", CURRENT_AVG),
        Field("Curr_fr", m.GRID_FREQUENCY),
        Field("TAP", m.ACTIVE_POWER),
        Field("TEI", m.ACTIVE_ENERGY_IMPORT),
        Field("LL_avg", VOLTAGE_LL_AVG),
    ),
)
