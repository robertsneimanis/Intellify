"""Split the spec's sample files into one valid JSON fixture per message.

The *_piemēri.json files hold several JSON documents separated by banner
lines and comments, so they cannot be loaded directly. Run from the repo root:

    python scripts/split_samples.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures"
SOURCES = {
    "milesight": "Milesight_piemēri.json",
    "viltrus": "Viltrus_piemēri.json",
    "wago": "Wago_piemēri.json",
}


def split_documents(text: str) -> list[tuple[str, dict]]:
    """Return (preceding banner text, document) for each top-level JSON object."""
    decoder = json.JSONDecoder()
    docs, pos = [], 0
    while (start := text.find("{", pos)) != -1:
        doc, end = decoder.raw_decode(text, start)
        docs.append((text[pos:start], doc))
        pos = end
    return docs


def slug(*parts: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", "_".join(parts).lower()).strip("_")


def label(family: str, banner: str, doc: dict) -> str:
    if family == "wago":
        return slug(doc["type"], doc["model"])
    if family == "viltrus":
        return slug(doc["name"])
    # Milesight payloads carry no model field; the banner above each one names it.
    match = re.search(r"##\s+([A-Za-z]\w*)", banner)
    return slug(match.group(1) if match else doc["devEUI"])


def main() -> None:
    for family, filename in SOURCES.items():
        text = (ROOT / filename).read_text(encoding="utf-8")
        target = OUT / family
        target.mkdir(parents=True, exist_ok=True)
        for banner, doc in split_documents(text):
            path = target / f"{label(family, banner, doc)}.json"
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
