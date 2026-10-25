"""Device models: what each source field means.

Every module in this package that defines a module-level `MODEL`
(`DeviceModel`) is registered automatically, so supporting a new device model
on an existing wire format means adding one module here. Shared metrics live
in `metrics.py`.
"""

import importlib
import pkgutil

from ingest.devices.base import DeviceModel, Metric
from ingest.model import Measurement, ParsedMessage, Reading


class UnknownDevice(Exception):
    """No device module matches the message."""


def _discover() -> list[DeviceModel]:
    models = []
    for info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if isinstance(getattr(module, "MODEL", None), DeviceModel):
            models.append(module.MODEL)
    return models


MODELS: list[DeviceModel] = _discover()


def catalog(models: list[DeviceModel] = MODELS) -> dict[str, Metric]:
    """All metrics used by the device models, keyed by metric key."""
    metrics: dict[str, Metric] = {}
    for model in models:
        for f in model.fields:
            existing = metrics.setdefault(f.metric.key, f.metric)
            if existing != f.metric:
                raise ValueError(f"metric {f.metric.key!r} is defined differently in {model.model}")
    return metrics


def resolve(source_format: str, message: ParsedMessage) -> DeviceModel:
    """Find the device module for a message: by explicit model, else by its fields."""
    candidates = [m for m in MODELS if m.source_format == source_format]
    if message.model is not None:
        for model in candidates:
            if model.model == message.model:
                return model
        raise UnknownDevice(f"no device module for {source_format} model {message.model!r}")

    fields = {r.source_field for r in message.readings}
    matches = [m for m in candidates if m.detect is not None and m.detect <= fields]
    if matches:
        best = max(len(m.detect) for m in matches)
        matches = [m for m in matches if len(m.detect) == best]
    if len(matches) != 1:
        names = [m.model for m in matches] or "none"
        raise UnknownDevice(f"cannot identify {source_format} device model (matches: {names})")
    return matches[0]


def to_measurements(
    model: DeviceModel, readings: list[Reading]
) -> tuple[list[Measurement], list[str]]:
    """Attach meaning to raw readings. Returns measurements and warnings.

    Fields with no mapping or with a value that cannot be converted are left
    out with a warning; the raw message keeps them for later reprocessing.
    """
    measurements, warnings = [], []
    for reading in readings:
        if reading.source_field in model.ignore:
            continue
        match = model.match(reading.source_field)
        if match is None:
            warnings.append(f"{reading.source_field}: no mapping in {model.model}, not stored")
            continue
        field, channel = match
        try:
            value = _convert(field.metric, reading.value, field.divisor)
        except ValueError as exc:
            warnings.append(f"{reading.source_field}: {exc}, not stored")
            continue
        issues = ["sensor_not_connected"] if reading.value in field.sentinels else []
        measurements.append(
            Measurement(field.metric.key, channel, reading.ts, value, reading.source_field, issues)
        )
    return measurements, warnings


_TRUE = {"on", "true", "1", "yes"}
_FALSE = {"off", "false", "0", "no"}


def _convert(metric: Metric, raw: object, divisor: float) -> float | bool | str:
    match metric.value_type:
        case "numeric":
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ValueError(f"expected a number, got {raw!r}")
            return raw / divisor
        case "boolean":
            if isinstance(raw, bool):
                return raw
            if raw in (0, 1) and isinstance(raw, int):
                return bool(raw)
            if isinstance(raw, str) and raw.lower() in _TRUE | _FALSE:
                return raw.lower() in _TRUE
            raise ValueError(f"expected an on/off value, got {raw!r}")
        case "text":
            if not isinstance(raw, str):
                raise ValueError(f"expected text, got {raw!r}")
            return raw
