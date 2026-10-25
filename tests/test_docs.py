from ingest import docgen


def test_data_model_doc_is_up_to_date():
    current = docgen.DOC.read_text(encoding="utf-8")
    assert current == docgen.updated(current), "run `python -m ingest.docgen`"
