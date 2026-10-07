from ad2v import ddl, store
from ad2v.resources import schema_dir

from helpers import FIXTURE

SPEC = FIXTURE.parent.parent / "docs" / "spec" / "ad2v-format-v0.6.md"


def test_every_column_is_marked_and_appendix_is_current():
    classes = ddl.column_classes()
    assert {
        "node_versions",
        "epoch_nodes",
        "edge_versions",
        "epoch_edges",
        "id_lineage",
        "link_state",
        "parse_cache",
        "links",
        "summaries",
        "narrations",
        "layout",
        "tours",
        "tour_stops",
        "node_status",
        "status_rollup",
        "workflow_step_nodes",
    } <= set(classes)
    volatile = {(t, c) for t, cols in classes.items() for c, k, _ in cols if k == "V"}
    assert volatile == {
        ("epoch_nodes", "span_start_line"),
        ("epoch_nodes", "span_end_line"),
        ("epoch_edges", "lines_json"),
    }
    text = SPEC.read_text(encoding="utf-8")
    assert ddl.render() in text, "run `python -m ad2v.ddl` to regenerate Appendix A"


def test_informative_columns():
    classes = ddl.column_classes()
    for table, cols in classes.items():
        for col, cls, _ in cols:
            if col == "created_at":
                assert cls == "I", table
            if col in ("model", "model_version", "prompt_hash", "input_hash"):
                assert cls == "I", (table, col)
            if col == "confidence":  # 1.0 for deterministic links (normative), LLM score otherwise
                assert cls in ("I", "N/I"), (table, col)
    assert {"created_at"} == store.EXCLUDED_COLUMNS


def test_schema_files_present():
    d = schema_dir()
    assert (d / "ad2v-v0.6.sql").is_file() and (d / "ir-v0.6.schema.json").is_file()
