from datetime import datetime

import pytest

from ingest.model import ParseError
from ingest.parsers import viltrus
from tests.conftest import RIGA


def test_el_uzskaite(load_fixture):
    message = viltrus.parse(load_fixture("viltrus/el_uzskaite_3.json"), RIGA)

    assert message.external_id == "105945"
    assert message.name == "EL_uzskaite_3"
    assert len(message.readings) == 19
    readings = {r.source_field: r for r in message.readings}
    assert readings["Sk1_aktiva_jauda"].value == 80.6681
    assert readings["61_frekvence"].value == 5001
    # Naive timestamps are read in the building's timezone.
    assert readings["Sk1_aktiva_jauda"].ts == datetime(2025, 6, 30, 15, 40, tzinfo=RIGA)
    assert message.warnings == []


def payload(**overrides):
    base = {
        "SN": "1",
        "header": {
            "recordCount": 1,
            "columns": {"0": {"id": "0", "name": "p", "dataType": "NUMBER", "format": "float"}},
        },
        "data": [{"ts": "2025-06-30T15:40:00.000", "f": {"0": {"v": 1.5}}}],
    }
    return base | overrides


def test_record_count_mismatch_is_warning():
    message = viltrus.parse(payload(data=[]), RIGA)

    assert message.warnings == ["recordCount is 1 but data has 0 rows"]


@pytest.mark.parametrize(
    "bad",
    [
        {"data": [{"ts": "2025-06-30T15:40:00", "f": {"9": {"v": 1}}}]},  # unknown column
        {"data": [{"ts": "2025-06-30T15:40:00", "f": {"0": {"v": "x"}}}]},  # NUMBER as text
        {"data": [{"ts": "2025-06-30T15:40:00+02:00", "f": {}}]},  # unexpected offset
        {"data": [{"ts": "bad", "f": {}}]},
        {"header": {}},
    ],
)
def test_rejects_malformed(bad):
    with pytest.raises(ParseError):
        viltrus.parse(payload(**bad), RIGA)
