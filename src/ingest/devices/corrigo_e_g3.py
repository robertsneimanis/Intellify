"""Regin Corrigo E (gen 3) air handling unit controller, read via a WAGO PLC.

Analog values are Modbus registers scaled x10 (`Temp_SupplyAir: 201` =
20.1 °C, next to `Setpoint_SupplyAirTemp: 200` = 20.0 °C). A raw 0 on a
sensor input means the sensor is not connected, so it is flagged as suspect.
"""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric


def state(key: str, description: str) -> Metric:
    return Metric(key, "state", None, "numeric", "state", description)


def temperature(key: str, description: str) -> Metric:
    return Metric(key, "temperature", "°C", "numeric", "gauge", description, -40, 80)


def setpoint(key: str, description: str, unit: str, low: float, high: float) -> Metric:
    return Metric(key, "setpoint", unit, "numeric", "gauge", description, low, high)


NOT_CONNECTED = frozenset({0})

MODEL = DeviceModel(
    source_format="wago",
    model="E_G3",
    device_type="ahu",
    manufacturer="Corrigo",
    description="Air handling unit controller",
    fields=(
        Field("UnitRunMode", state("ahu_unit_run_mode", "Unit run mode (Corrigo enum)")),
        Field("RunMode", state("ahu_run_mode", "Run mode (Corrigo enum)")),
        Field("Control_Mode", state("ahu_control_mode", "Temperature control mode (Corrigo enum)")),
        Field(
            "Temp_SupplyAir",
            temperature("supply_air_temperature", "Supply air temperature"),
            divisor=10,
            sentinels=NOT_CONNECTED,
        ),
        Field(
            "Temp_ExtractAir",
            temperature("extract_air_temperature", "Extract air temperature"),
            divisor=10,
            sentinels=NOT_CONNECTED,
        ),
        Field(
            r"Temp_Room(?P<channel>\d+)",
            temperature("room_temperature", "Room temperature, channel = room sensor"),
            divisor=10,
            sentinels=NOT_CONNECTED,
        ),
        Field("CO2_Level", m.CO2, sentinels=NOT_CONNECTED),
        Field(
            "Humidity_Duct",
            Metric(
                "duct_relative_humidity",
                "relative_humidity",
                "%",
                "numeric",
                "gauge",
                "Relative humidity in the air duct",
                0,
                100,
            ),
            divisor=10,
            sentinels=NOT_CONNECTED,
        ),
        Field("Humidity_Room", m.RELATIVE_HUMIDITY, divisor=10, sentinels=NOT_CONNECTED),
        Field(
            "Setpoint_SupplyAirTemp",
            setpoint(
                "supply_air_temperature_setpoint", "Supply air temperature setpoint", "°C", 5, 40
            ),
            divisor=10,
        ),
        Field(
            "Setpoint_Humidity",
            setpoint("humidity_setpoint", "Relative humidity setpoint", "%", 0, 100),
            divisor=10,
        ),
        Field(
            "Setpoint_CO2",
            # Raw value 3 in the sample does not fit ppm; unit and scale unconfirmed.
            setpoint(
                "co2_setpoint", "CO2 setpoint (raw register, scale unknown)", None, None, None
            ),
        ),
        Field(
            r"Setpoint_(?P<channel>Supp|Exh)(?i:eco)",
            setpoint(
                "fan_speed_setpoint_eco",
                "Fan speed setpoint in economy mode, channel = Supp (supply) / Exh (exhaust)",
                "%",
                0,
                100,
            ),
            divisor=10,
        ),
        Field(
            r"Setpoint_(?P<channel>Supp|Exh)Normal",
            setpoint(
                "fan_speed_setpoint_normal",
                "Fan speed setpoint in normal mode, channel = Supp (supply) / Exh (exhaust)",
                "%",
                0,
                100,
            ),
            divisor=10,
        ),
        Field(
            "Alarm_AckById",
            state("ahu_alarm_ack_by", "Id of the last alarm acknowledged (255 = none)"),
        ),
        Field(r"Alarm_(?P<channel>\w+)", m.ALARM),
    ),
)
