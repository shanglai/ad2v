"""P10 M1 (ADR-0073): the zero-config warning and test-name prefixes derived from the specs."""

from __future__ import annotations

import json
from pathlib import Path

from ad2v import pipeline, store
from ad2v.cli import main
from ad2v.mcp.slices import meta as slice_meta

from helpers import FIXTURE, write_tree

ROOT = Path(__file__).resolve().parent.parent
BF = ROOT / "fixtures" / "brownfield-es"


def test_zero_config_brownfield_names_every_condition(tmp_path, capsys):
    out = tmp_path / "bf.ad2v"
    assert main(["extract", "--repo", str(BF), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert (
        "WARNING: This map was built without configuration; 4 things may be wrong. Run `ad2v init`." in text
    )
    for want in (
        "settings.API_PREFIX",
        "src/backend, src/frontend",
        "HU, RF, RNF",
        "infrastructure as code found: infra",
    ):
        assert want in text, want
    conn = store.open_readonly(out)
    try:
        m = store.read_meta(conn)
        kinds = [w["kind"] for w in json.loads(m["unconfigured_warnings"])]
        assert kinds == [
            "unresolved_route_prefixes",
            "fallback_container",
            "test_prefixes_derived",
            "iac_present",
        ]
        assert json.loads(m["derived_test_name_prefixes"]) == ["HU", "RF", "RNF"]
        assert len(slice_meta(conn)["unconfigured"]) == 4  # the viewer's banner
        # informative meta: the canonical dump does not carry them
        cls = dict(
            conn.execute(
                "SELECT key, class FROM meta WHERE key LIKE '%prefixes' OR key LIKE 'unconf%'"
            ).fetchall()
        )
        assert set(cls.values()) == {"I"}
    finally:
        conn.close()


def test_derived_prefixes_link_test_names_without_a_manifest():
    res = pipeline.build(BF)
    st = {res.graph.nodes[k].qualified_name: v.status for k, v in res.pairing.statuses.items()}
    assert st["RF-002"] == "implemented" and st["RF-003"] == "implemented"
    assert res.config.derived_test_prefixes == ("HU", "RF", "RNF")
    assert res.config.config_json["effective"]["derived_test_prefixes"] == ["HU", "RF", "RNF"]


def test_a_manifest_means_no_warning_and_known_prefixes_change_nothing(tmp_path):
    res = pipeline.build(FIXTURE)  # payments-recon has an ad2v.yaml and only REQ/CMP ids
    assert res.unconfigured == [] and res.config.derived_test_prefixes == ()
    assert "derived_test_prefixes" not in res.config.config_json["effective"]


def test_a_clean_small_repo_has_no_warning(tmp_path):
    write_tree(
        tmp_path / "r",
        {
            "app.py": "def f():\n    return 1\n",
            "specs/c.md": "## Component: App {#CMP-001}\n- [REQ-001] The system shall return one.\n",
        },
    )
    res = pipeline.build(tmp_path / "r")
    assert res.unconfigured == []
