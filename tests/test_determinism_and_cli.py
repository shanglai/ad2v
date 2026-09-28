"""Determinism, ID stability, validation and CLI (prompt §8)."""

import shutil
import sqlite3
import subprocess
import sys

import pytest

from ad2v import dump, pipeline
from ad2v.cli import main
from ad2v.validate import validate

from helpers import FIXTURE

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".feature", ".toml", ".json"}


def _extract(repo, out):
    pipeline.extract_to_file(repo, repo / "specs", out)
    return dump.canonical_dump(out)


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
    rows = conn.execute("SELECT id, qualified_name, content_hash, subtree_hash FROM nodes").fetchall()
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
    assert {after[i][0] for i in new_ids} == {"api/recon_api/matching.py::describe_tolerance"}
    assert set(before) <= set(after), "no existing id may disappear or change"

    ancestors = {
        "api/recon_api/matching.py",
        "api/recon_api",
        "container:api",
        "payments-recon",
    }
    for nid, (qname, content, subtree) in before.items():
        if qname in ancestors:
            assert after[nid][2] != subtree, f"subtree_hash of ancestor {qname} must change"
        elif qname.startswith("api/recon_api/matching.py::"):
            # siblings (some moved down by the insertion) keep their content hash
            assert after[nid][1] == content
    changed_subtrees = {before[i][0] for i in before if before[i][2] != after[i][2]}
    assert changed_subtrees == ancestors


def test_validate_ok_and_detects_corruption(tmp_path):
    out = tmp_path / "p.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out)
    assert validate(out) == []
    conn = sqlite3.connect(out)
    conn.execute("UPDATE nodes SET subtree_hash = ? WHERE kind = 'system'", ("0" * 64,))
    conn.execute("DELETE FROM glyphs WHERE node_id = (SELECT id FROM nodes WHERE kind = 'queue' LIMIT 1)")
    conn.execute("UPDATE meta SET value = '9.9' WHERE key = 'format_version'")
    conn.execute("UPDATE nodes SET qualified_name = 'tampered' WHERE kind = 'datastore'")
    conn.commit()
    conn.close()
    problems = "\n".join(validate(out))
    assert "format_version" in problems
    assert "without a glyph" in problems
    assert "subtree_hash" in problems
    assert "id does not match" in problems


def test_cli_commands(tmp_path, capsysbinary):
    out = tmp_path / "p.ad2v"
    assert main(["extract", "--repo", str(FIXTURE), "--spec", str(FIXTURE / "specs"), "--out", str(out)]) == 0
    text = capsysbinary.readouterr().out.decode("utf-8")
    for needle in ("io_in_loop", "unbounded_retry", "POST /v1/reconciliations", "REQ-099", "Workflows"):
        assert needle in text
    assert main(["validate", str(out)]) == 0
    assert capsysbinary.readouterr().out.startswith(b"OK")
    assert main(["dump", str(out), "--canonical"]) == 0
    assert capsysbinary.readouterr().out.decode("utf-8") == dump.canonical_dump(out)
    assert main(["inspect", str(out), "--risk", "llm_in_loop"]) == 0
    listing = capsysbinary.readouterr().out.decode("utf-8")
    assert "classify_unmatched@loop#1" in listing and "match_batch" not in listing
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
    # semantic change: different hash and epoch id, and the canonical dump shows it
    edited = tmp_path / "python.yaml"
    edited.write_text(python_rules_path().read_text(encoding="utf-8") + "\n# local tweak\n", encoding="utf-8")
    changed = pipeline.build(FIXTURE, FIXTURE / "specs", rules_path=edited)
    assert changed.epoch.rules_hash != base.epoch.rules_hash
    assert changed.epoch.epoch_id != base.epoch.epoch_id
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, rules_path=edited)
    epoch_rows = [ln for ln in dump.canonical_dump(out).splitlines() if '"table":"epochs"' in ln]
    assert len(epoch_rows) == 1 and f'"rules_hash":"{changed.epoch.rules_hash}"' in epoch_rows[0]
