from ad2v import ddl, store
from ad2v.resources import schema_dir

from helpers import FIXTURE

SPEC = FIXTURE.parent.parent / "docs" / "spec" / "ad2v-format-v0.1.md"


def test_every_column_is_marked_and_appendix_is_current():
    classes = ddl.column_classes()
    assert {"nodes", "edges", "links", "summaries", "narrations", "layout", "tours", "tour_stops"} <= set(
        classes
    )
    text = SPEC.read_text(encoding="utf-8")
    assert ddl.render() in text, "run `python -m ad2v.ddl` to regenerate Appendix A"


def test_informative_columns():
    classes = ddl.column_classes()
    for table, cols in classes.items():
        for col, cls, _ in cols:
            if col == "created_at":
                assert cls == "I", table
            if col in ("model", "model_version", "prompt_hash", "input_hash", "confidence"):
                assert cls == "I", (table, col)
    assert {"created_at"} == store.EXCLUDED_COLUMNS


def test_schema_files_present():
    d = schema_dir()
    assert (d / "ad2v-v0.1.sql").is_file() and (d / "ir-v0.1.schema.json").is_file()
