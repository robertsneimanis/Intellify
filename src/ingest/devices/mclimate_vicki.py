"""MClimate Vicki: LoRaWAN smart radiator thermostat (valve actuator)."""

from ingest.devices import metrics as m
from ingest.devices.base import DeviceModel, Field, Metric


def flag(key: str, description: str) -> Metric:
    return Metric(key, "state", None, "boolean", "state", description)


TARGET_TEMPERATURE = Metric(
    "target_temperature",
    "temperature",
    "°C",
    "numeric",
    "gauge",
    "Temperature setpoint",
    5,
    30,
)
VALVE_OPENING = Metric(
    "valve_opening",
    "position",
    "%",
    "numeric",
    "gauge",
    "Valve opening (0 = closed, 100 = fully open)",
    0,
    100,
)
MOTOR_POSITION = Metric(
    "motor_position",
    "position",
    "steps",
    "numeric",
    "gauge",
    "Valve motor position in motor steps",
    0,
    1000,
)
MOTOR_RANGE = Metric(
    "motor_range",
    "position",
    "steps",
    "numeric",
    "gauge",
    "Calibrated full motor travel in steps",
    0,
    1000,
)

MODEL = DeviceModel(
    source_format="milesight",
    model="Vicki",
    device_type="radiator_valve",
    manufacturer="MClimate",
    description="Smart radiator thermostat",
    detect=frozenset({"motorPosition", "targetTemperature"}),
    ignore=frozenset({"newVersion"}),  # payload format flag, not a measurement
    fields=(
        Field("sensorTemperature", m.AIR_TEMPERATURE),
        Field("relativeHumidity", m.RELATIVE_HUMIDITY),
        Field("targetTemperature", TARGET_TEMPERATURE),
        Field("openProcentage", VALVE_OPENING),
        Field("motorPosition", MOTOR_POSITION),
        Field("motorRange", MOTOR_RANGE),
        Field("batteryVoltage", m.BATTERY_VOLTAGE),
        Field("openWindow", flag("open_window_detected", "Open window detected")),
        Field("childLock", flag("child_lock", "Child lock enabled")),
        Field("attachedBackplate", flag("backplate_attached", "Device mounted on its backplate")),
        Field("perceiveAsOnline", flag("online", "Device considers itself online")),
        Field("brokenSensor", flag("fault_broken_sensor", "Fault: temperature sensor broken")),
        Field("calibrationFailed", flag("fault_calibration", "Fault: valve calibration failed")),
        Field(
            "highMotorConsumption",
            flag("fault_high_motor_current", "Fault: motor current too high"),
        ),
        Field(
            "lowMotorConsumption",
            flag("fault_low_motor_current", "Fault: motor current too low"),
        ),
    ),
)
