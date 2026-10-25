"""Regenerate the device mapping tables in docs/data-model.md from the device modules.

    python -m ingest.docgen

Only the part between the `generated` markers is replaced; a test fails when
it is out of date, so the documentation cannot drift from the code.
"""

import re
from pathlib import Path

from ingest import devices
from ingest.devices.base import DeviceModel, Field

DOC = Path(__file__).resolve().parents[2] / "docs" / "data-model.md"
START, END = "<!-- generated:start -->", "<!-- generated:end -->"


def _pattern(field: Field) -> str:
    text = re.sub(r"\(\?P<channel>(?:[^()]|\([^()]*\))*\)", "<channel>", field.pattern)
    text = re.sub(r"\(\?i:([^()]*)\)", r"\1", text)
    return text.replace("\\d", "N").replace("\\", "")


def _range(field: Field) -> str:
    low, high = field.metric.min_valid, field.metric.max_valid
    if low is None and high is None:
        return ""
    return f"{'' if low is None else f'{low:g}'} … {'' if high is None else f'{high:g}'}"


def _scale(field: Field) -> str:
    parts = [f"÷{field.divisor:g}"] if field.divisor != 1 else []
    if field.sentinels:
        parts.append("raw " + "/".join(map(str, sorted(field.sentinels))) + " = no reading")
    return ", ".join(parts)


def _model_section(model: DeviceModel) -> str:
    lines = [
        f"### {model.manufacturer or ''} {model.model}".replace("  ", " "),
        "",
        f"{model.description}. Format `{model.source_format}`, device type `{model.device_type}`.",
        "",
        "| Source field | Metric | Unit | Kind | Scale | Valid range | Meaning |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in model.fields:
        m = f.metric
        row = [
            f"`{_pattern(f)}`",
            f"`{m.key}`",
            m.unit or "",
            m.kind,
            _scale(f),
            _range(f),
            m.description,
        ]
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    if model.ignore:
        lines += [
            "",
            "Not stored as measurements: " + ", ".join(f"`{f}`" for f in sorted(model.ignore)),
        ]
    return "\n".join(lines)


def render() -> str:
    models = sorted(devices.MODELS, key=lambda m: (m.source_format, m.model))
    return "\n\n".join(_model_section(m) for m in models)


def updated(doc: str) -> str:
    before, rest = doc.split(START, 1)
    _, after = rest.split(END, 1)
    return f"{before}{START}\n\n{render()}\n\n{END}{after}"


def main() -> None:
    DOC.write_text(updated(DOC.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"updated {DOC}")


if __name__ == "__main__":
    main()
