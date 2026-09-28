"""Determinism, ID stability, validation and CLI (prompt §8)."""

import json
import shutil
import sqlite3
import subprocess
import sys

import pytest

from ad2v import dump, pipeline
from ad2v.cli import main
from ad2v.validate import validate

from helpers import FIXTURE, JUNIT

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".feature", ".toml", ".json", ".xml"}


def _extract(repo, out, normative_only=True):
    pipeline.extract_to_file(repo, repo / "specs", out, test_results=[repo / "test-results" / "junit.xml"])
    return dump.canonical_dump(out, normative_only=normative_only)


def _copy_fixture(dst, crlf=False, bom_on=()):
    shutil.copytree(FIXTURE, dst)
    if crlf:
        for p in sorted(dst.rglob("*")):
            if p.is_file() and p.suffix in TEXT_SUFFIXES:
                data = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if p.name in bom_on:
                    data = b"\xef\xbb\xbf" + data
                p.write_bytes(data)
    return dst


def test_extract_twice_identical(tmp_path):
    a = _extract(FIXTURE, tmp_path / "a.ad2v")
    b = _extract(FIXTURE, tmp_path / "b.ad2v")
    assert a == b
    assert len(a.splitlines()) > 300


def test_crlf_bom_copy_identical(tmp_path):
    base = _extract(FIXTURE, tmp_path / "base.ad2v")
    copy = _copy_fixture(tmp_path / "crlf" / "payments-recon", crlf=True, bom_on=("db.py", "components.md"))
    assert b"\r\n" in (copy / "api" / "recon_api" / "db.py").read_bytes()
    assert _extract(copy, tmp_path / "crlf.ad2v") == base


def test_checkout_directory_name_does_not_matter(tmp_path):
    base = _extract(FIXTURE, tmp_path / "base.ad2v")
    copy = _copy_fixture(tmp_path / "elsewhere" / "renamed-checkout")
    assert _extract(copy, tmp_path / "renamed.ad2v") == base


def _nodes(path):
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT id, side || ':' || qualified_name, content_hash, subtree_hash FROM nodes"
    ).fetchall()
    conn.close()
    return {r[0]: r[1:] for r in rows}


def _table(path, sql):
    conn = sqlite3.connect(path)
    rows = conn.execute(sql).fetchall()
    conn.close()
    return {r[0]: r[1:] for r in rows}


def test_id_stability_after_adding_unrelated_function(tmp_path):
    repo = _copy_fixture(tmp_path / "repo" / "payments-recon")
    before_path = tmp_path / "before.ad2v"
    _extract(repo, before_path)
    before = _nodes(before_path)

    target = repo / "api" / "recon_api" / "matching.py"
    src = target.read_text(encoding="utf-8")
    anchor = "\n\n# ad2v: REQ-003\n"
    assert anchor in src
    target.write_text(
        src.replace(anchor, "\n\ndef describe_tolerance() -> str:\n    return 'one cent'\n" + anchor),
        encoding="utf-8",
        newline="\n",
    )
    after_path = tmp_path / "after.ad2v"
    _extract(repo, after_path)
    after = _nodes(after_path)

    new_ids = set(after) - set(before)
    assert {after[i][0] for i in new_ids} == {"code:api/recon_api/matching.py::describe_tolerance"}
    assert set(before) <= set(after), "no existing id may disappear or change"

    ancestors = {
        "code:api/recon_api/matching.py",
        "code:api/recon_api",
        "code:container:api",
        "code:payments-recon",
    }
    for nid, (qname, content, subtree) in before.items():
        if qname in ancestors:
            assert after[nid][2] != subtree, f"subtree_hash of ancestor {qname} must change"
        elif qname.startswith("code:api/recon_api/matching.py::"):
            # siblings (some moved down by the insertion) keep their content hash
            assert after[nid][1] == content
    changed_subtrees = {before[i][0] for i in before if before[i][2] != after[i][2]}
    assert changed_subtrees == ancestors

    # pairing is unaffected by an edit outside paired nodes: same links, same statuses
    links_sql = "SELECT link_id, status, method, evidence_json FROM links"
    assert _table(before_path, links_sql) == _table(after_path, links_sql)
    st_sql = "SELECT node_id, status, reasons_json FROM node_status"
    st_before, st_after = _table(before_path, st_sql), _table(after_path, st_sql)
    assert {k: v for k, v in st_after.items() if k in st_before} == st_before
    roll_sql = "SELECT node_id, counts_json FROM status_rollup"
    r_before, r_after = _table(before_path, roll_sql), _table(after_path, roll_sql)
    assert {before[k][0] for k in r_before if r_before[k] != r_after[k]} == ancestors


def test_validate_ok_and_detects_corruption(tmp_path):
    out = tmp_path / "p.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, test_results=[JUNIT])
    assert validate(out) == []
    conn = sqlite3.connect(out)
    conn.execute("UPDATE node_versions SET subtree_hash = ? WHERE kind = 'system'", ("0" * 64,))
    conn.execute("DELETE FROM glyphs WHERE node_id = (SELECT id FROM nodes WHERE kind = 'queue' LIMIT 1)")
    conn.execute("UPDATE node_versions SET qualified_name = 'tampered' WHERE kind = 'datastore'")
    conn.execute(
        "DELETE FROM node_status WHERE node_id = (SELECT id FROM nodes WHERE kind = 'queue' LIMIT 1)"
    )
    conn.execute("DELETE FROM workflow_step_nodes WHERE seq = 0")
    conn.execute(
        "UPDATE status_rollup SET counts_json = '{}'"
        " WHERE node_id = (SELECT id FROM nodes WHERE kind = 'system')"
    )
    conn.execute("UPDATE links SET link_id = 'l_00000000000000000000' WHERE rowid = 1")
    # an edge whose endpoint is not a node of the epoch (endpoints are checked, not FOREIGN KEYs)
    conn.execute(
        "UPDATE edge_versions SET dst = 'n_00000000000000000000' WHERE kind = 'calls' AND vid = "
        "(SELECT MIN(vid) FROM edge_versions WHERE kind = 'calls')"
    )
    conn.commit()
    conn.close()
    problems = "\n".join(validate(out))
    assert "without a glyph" in problems
    assert "edges.dst: 1 id(s) not a node of this epoch" in problems
    assert "key does not match its payload" in problems  # version rows are content-addressed
    assert "subtree_hash" in problems
    assert "id does not match" in problems
    assert "node_status covers" in problems
    assert "workflow_step_nodes" in problems
    assert "status_rollup" in problems
    assert "link_id(spec, code, method)" in problems


def test_validate_rejects_old_format(tmp_path):
    out = tmp_path / "p.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out)
    conn = sqlite3.connect(out)
    conn.execute("UPDATE meta SET value = '0.1' WHERE key = 'format_version'")
    conn.commit()
    conn.close()
    problems = validate(out)
    assert len(problems) == 1 and "0.1" in problems[0] and "re-run `ad2v extract`" in problems[0]


def test_cli_commands(tmp_path, capsysbinary):
    out = tmp_path / "p.ad2v"
    argv = ["extract", "--repo", str(FIXTURE), "--spec", str(FIXTURE / "specs"), "--out", str(out)]
    assert main([*argv, "--test-results", str(JUNIT)]) == 0
    text = capsysbinary.readouterr().out.decode("utf-8")
    for needle in (
        "hit rate",
        "unbounded_retry",
        "POST /v1/reconciliations",
        "REQ-099",
        "workflows",
        "Status counts",
        "Top 5 of 5 risky behaviors",
        "1 unmatched",
        "test_removed_export_endpoint",
    ):
        assert needle in text
    assert main(["validate", str(out)]) == 0
    assert capsysbinary.readouterr().out.startswith(b"OK")
    assert main(["dump", str(out), "--canonical"]) == 0
    assert capsysbinary.readouterr().out.decode("utf-8") == dump.canonical_dump(out)
    assert main(["inspect", str(out), "--risk", "llm_in_loop"]) == 0
    listing = capsysbinary.readouterr().out.decode("utf-8")
    assert "classify_unmatched@loop#" in listing and "match_batch" not in listing
    assert main(["inspect", str(out), "--top-risk", "2"]) == 0
    top = capsysbinary.readouterr().out.decode("utf-8").splitlines()
    assert len(top) == 4 and "fetch_statement@retry#" in top[2] and top[2].startswith("1 ")
    assert main(["status", str(out), "--status", "drift"]) == 0
    drift = capsysbinary.readouterr().out.decode("utf-8")
    assert "GET /reconciliations/{run_id}/unmatched" in drift and "orphan" not in drift
    assert main(["status", str(out), "--side", "code", "--format", "json"]) == 0
    items = json.loads(capsysbinary.readouterr().out)
    assert items and all(i["side"] == "code" and i["status"] != "none" for i in items)
    assert main(["status", str(out), "--all"]) == 0
    assert b"none " in capsysbinary.readouterr().out
    assert main(["dump", str(out), "--normative-only"]) == 0
    assert capsysbinary.readouterr().out.decode("utf-8") == dump.canonical_dump(out, normative_only=True)
    html = tmp_path / "tokens.html"
    assert main(["preview-tokens", "--out", str(html)]) == 0
    capsysbinary.readouterr()
    assert html.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert main(["inspect", str(out), "--node", "api/recon_api/matching.py::match_batch"]) == 0
    detail = capsysbinary.readouterr().out.decode("utf-8")
    assert '"annotated_as -> REQ-002 (x1)"' in detail and '"base_shape": "rounded_box"' in detail
    assert main(["inspect", str(out), "--kind", "queue"]) == 0
    assert b"queue:env:RECON_EVENTS_TOPIC" in capsysbinary.readouterr().out
    assert main(["inspect", str(out), "--node", "nope"]) == 1


def test_cli_dump_stdout_is_lf_only_in_subprocess(tmp_path):
    out = tmp_path / "p.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out)
    proc = subprocess.run(
        [sys.executable, "-m", "ad2v.cli", "dump", str(out), "--canonical"], capture_output=True, check=True
    )
    assert b"\r\n" not in proc.stdout
    assert proc.stdout.decode("utf-8") == dump.canonical_dump(out)


def test_manifest_errors(tmp_path):
    from ad2v.manifest import ManifestError, load

    with pytest.raises(ManifestError):
        load(tmp_path, tmp_path / "missing.yaml")
    (tmp_path / "ad2v.yaml").write_text("containers:\n  - paths: [x]\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load(tmp_path)


def test_readers_never_create_files(tmp_path, capsys):
    missing = tmp_path / "missing.ad2v"
    assert main(["validate", str(missing)]) == 2
    assert main(["dump", str(missing)]) == 2
    assert not missing.exists()
    junk = tmp_path / "junk.ad2v"
    junk.write_bytes(b"not sqlite at all")
    assert main(["inspect", str(junk)]) == 2
    assert "not an ad2v file" in capsys.readouterr().err


def test_rules_file_change_changes_rules_hash(tmp_path):
    from ad2v.resources import python_rules_path

    base = pipeline.build(FIXTURE, FIXTURE / "specs")
    # CRLF-only change: same normalized content, same hash
    crlf = tmp_path / "crlf.yaml"
    crlf.write_bytes(python_rules_path().read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert (
        pipeline.build(FIXTURE, FIXTURE / "specs", rules_path=crlf).epoch.rules_hash == base.epoch.rules_hash
    )
    # comment-only change: rules_hash is over canonicalized content (ADR-0012), so it does not move
    comment = tmp_path / "comment.yaml"
    comment.write_text(
        python_rules_path().read_text(encoding="utf-8") + "\n# local tweak\n", encoding="utf-8"
    )
    assert (
        pipeline.build(FIXTURE, FIXTURE / "specs", rules_path=comment).epoch.rules_hash
        == base.epoch.rules_hash
    )
    # semantic change: different hash and epoch id, and the canonical dump shows it
    edited = tmp_path / "python.yaml"
    text = python_rules_path().read_text(encoding="utf-8")
    assert "    fan_out: 2\n" in text
    edited.write_text(text.replace("    fan_out: 2\n", "    fan_out: 2.5\n"), encoding="utf-8")
    changed = pipeline.build(FIXTURE, FIXTURE / "specs", rules_path=edited)
    assert changed.epoch.rules_hash != base.epoch.rules_hash
    assert changed.epoch.epoch_id != base.epoch.epoch_id
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, rules_path=edited)
    epoch_rows = [ln for ln in dump.canonical_dump(out).splitlines() if '"table":"epochs"' in ln]
    assert len(epoch_rows) == 1 and f'"rules_hash":"{changed.epoch.rules_hash}"' in epoch_rows[0]
