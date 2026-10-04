"""P8 M1: the extractor plug-in API (ADR-0063..0065): compatibility, discovery and opt-in,
identity in the epoch, isolation (failures, timeouts, strict), the parse-cache key, the rules
split, the conformance kit, and the out-of-tree examples (loaded from examples/ in-process)."""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest
import yaml

from ad2v import admin, ids, pipeline, plugins, rules, store
from ad2v.api import (
    API_VERSION,
    CodeFacts,
    ExtractContext,
    ExtractOutput,
    FileAccessError,
    FileAccessor,
    Node,
    api_compatible,
)
from ad2v.extract.code.plugin import RULES_DIR
from ad2v.manifest import Config, ManifestError, from_data
from ad2v.testing import conformance

from helpers import FIXTURE, write_tree

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples" / "plugins"
PRE_P8_RULES_HASH = "40e0c80363b1"  # python.yaml before the split (rules_hash prefix, P7)


# ---------------------------------------------------------------------------------------------
# fake third-party plug-ins
# ---------------------------------------------------------------------------------------------


class ToyExtractor:
    """Claims *.toy; one module node per file and one function per `def <name>` line."""

    api_version = API_VERSION
    name = "toy"
    version = "1.0.0"
    languages = ("toy",)
    file_patterns = ("*.toy",)
    rules_files: tuple[Path, ...] = ()
    node_kinds = frozenset({"module", "function"})
    edge_kinds: frozenset[str] = frozenset()
    mode = "ok"  # ok | raise | hang | outside | undeclared | random

    def extract(self, ctx: ExtractContext) -> ExtractOutput:
        if self.mode == "raise":
            raise RuntimeError("boom")
        if self.mode == "hang":
            time.sleep(5)
        if self.mode == "outside":
            with contextlib.suppress(FileAccessError):
                ctx.files.read_text("../secret.txt")
        facts = CodeFacts()
        for f in ctx.files:
            facts.files_read[f.path] = f.content_hash
            mod = ctx.graph.add_node(
                Node(
                    "code",
                    "module",
                    f.path,
                    f.path,
                    parent_id=ctx.layout.parent_for_module(f.path),
                    path=f.path,
                    content_hash=f.content_hash,
                    attrs={"language": "toy"},
                )
            )
            for i, line in enumerate(f.text.split("\n"), 1):
                if line.startswith("def "):
                    nm = line[4:].strip()
                    if self.mode == "random":
                        nm += str(time.perf_counter_ns())
                    kind = "class" if self.mode == "undeclared" else "function"
                    ctx.graph.add_node(
                        Node(
                            "code",
                            kind,
                            nm,
                            f"{f.path}::{nm}",
                            parent_id=mod.id,
                            path=f.path,
                            span_start_line=i,
                            span_end_line=i,
                            content_hash=ids.content_hash(line),
                        )
                    )
        return ExtractOutput(facts=facts)


class ToyPack:
    api_version = API_VERSION
    name = "toy-pack"
    version = "0.1.0"
    attaches_to = ("python",)
    frameworks = ("bottle",)
    file_patterns: tuple[str, ...] = ()
    rules_files: tuple[Path, ...] = (
        EXAMPLES / "bottle-framework-pack" / "src" / "ad2v_bottle_pack" / "bottle.yaml",
    )
    node_kinds: frozenset[str] = frozenset()
    edge_kinds: frozenset[str] = frozenset()
    fail = False

    def post_extract(self, ctx) -> None:
        if self.fail:
            for n in list(ctx.graph.nodes.values()):
                n.attrs["poisoned"] = True  # must be discarded with the failed hook
            raise ValueError("pack failed")


def _with(monkeypatch, *objs, error: str | None = None) -> None:
    base = [d for d in plugins.discover() if d.builtin]
    extra = []
    for o in objs:
        kind = "framework" if hasattr(o, "attaches_to") else "extractor"
        extra.append(
            plugins.Discovered(kind, o.name, False, "toy-dist", "1.0", "toy:obj", lambda o=o: o, error=error)
        )
    monkeypatch.setattr(plugins, "discover", lambda: [*base, *extra])


def _toy_repo(tmp_path: Path, manifest: str | None = None) -> Path:
    repo = tmp_path / "toyrepo"
    write_tree(repo, {"svc/a.toy": "def alpha\ndef beta\n", "svc/b.py": "def gamma():\n    return 1\n"})
    if manifest:
        (repo / "ad2v.yaml").write_text(manifest, encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------------------------
# API version policy
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plugin,core,ok",
    [
        ("1.0", "1.0", True),
        ("1.0", "1.3", True),
        ("1.4", "1.3", False),
        ("0.9", "1.0", True),
        ("1.2", "2.0", True),
        ("0.9", "2.0", False),
        ("3.0", "2.0", False),
        ("one", "1.0", False),
    ],
)
def test_api_compatibility_policy(plugin, core, ok):
    assert api_compatible(plugin, core)[0] is ok


def test_builtins_are_discovered_and_always_active():
    found = {d.name: d for d in plugins.discover()}
    assert found["python"].builtin and found["python-frameworks"].builtin
    act = plugins.resolve(Config())
    assert [e.name for e in act.extractors] == ["python"]
    assert [p.name for p in act.packs] == ["python-frameworks"]
    recs = act.epoch_rules["plugins"]
    assert [(r["kind"], r["name"]) for r in recs] == [
        ("extractor", "python"),
        ("framework", "python-frameworks"),
    ]
    assert all(r["api_version"] == API_VERSION for r in recs)


def test_rules_split_keeps_the_python_rules_identical():
    """python.yaml + python-frameworks.yaml (pack merge) == the pre-P8 python.yaml."""
    merged = rules.pack_merge(
        rules.load_yaml(RULES_DIR / "python.yaml"), rules.load_yaml(RULES_DIR / "python-frameworks.yaml")
    )
    assert rules.rules_hash(merged).startswith(PRE_P8_RULES_HASH)
    act = plugins.resolve(Config())
    assert act.effective_hash["python"].startswith(PRE_P8_RULES_HASH)
    assert "ports" not in rules.load_yaml(RULES_DIR / "python.yaml")
    assert rules.load()["_hash"] == act.epoch_rules["_hash"]


def test_pack_merge_unions_lists_and_merges_mappings():
    base = {"a": [1, 2], "m": {"x": 1, "l": ["p"]}, "s": "old"}
    frag = {"a": [2, 3], "m": {"y": 2, "l": ["q", "p"]}, "s": "new"}
    assert rules.pack_merge(base, frag) == {
        "a": [1, 2, 3],
        "m": {"x": 1, "y": 2, "l": ["p", "q"]},
        "s": "new",
    }


# ---------------------------------------------------------------------------------------------
# opt-in, identity, epochs
# ---------------------------------------------------------------------------------------------


def test_installed_plugins_are_inactive_until_enabled(monkeypatch, tmp_path):
    _with(monkeypatch, ToyExtractor())
    repo = _toy_repo(tmp_path)
    off = pipeline.build(repo)
    assert "toy" not in off.rules["plugins"].__repr__()
    assert not [n for n in off.graph.nodes.values() if n.attrs.get("language") == "toy"]
    on = pipeline.build(repo, extractors=["toy"])
    assert {n.qualified_name for n in on.graph.nodes.values() if n.kind == "function"} >= {
        "svc/a.toy::alpha",
        "svc/a.toy::beta",
    }
    assert on.epoch.epoch_id != off.epoch.epoch_id and on.epoch.rules_hash != off.epoch.rules_hash
    assert on.epoch.repo_tree_hash != off.epoch.repo_tree_hash  # *.toy files became inputs
    assert on.epoch.config_hash == off.epoch.config_hash
    via_manifest = pipeline.build(_toy_repo(tmp_path / "m", "extractors:\n  enabled: [toy]\n"))
    assert via_manifest.epoch.rules_hash == on.epoch.rules_hash
    assert via_manifest.epoch.config_hash == off.epoch.config_hash  # extractors.* is not config


def test_plugin_version_change_makes_a_new_epoch_of_kind_rules(monkeypatch, tmp_path):
    t = ToyExtractor()
    _with(monkeypatch, t)
    repo = _toy_repo(tmp_path, "extractors:\n  enabled: [toy]\n")
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(repo, None, out)
    assert pipeline.extract_to_file(repo, None, out, into=True).unchanged
    t2 = ToyExtractor()
    t2.version = "1.0.1"
    _with(monkeypatch, t2)
    res = pipeline.extract_to_file(repo, None, out, into=True)
    assert not res.unchanged and res.epoch.change_kind == "rules"


def test_enabling_an_unknown_plugin_fails(tmp_path):
    with pytest.raises(plugins.PluginError, match="not installed"):
        pipeline.build(_toy_repo(tmp_path), extractors=["nope"])


def test_manifest_validation():
    with pytest.raises(ManifestError):
        from_data({"extractors": ["toy"]}, None)
    with pytest.raises(ManifestError):
        from_data({"extractors": {"enabled": [1]}}, None)
    assert from_data({"extractors": {"enabled": "toy"}}, None).extractors_enabled == ("toy",)


def test_shadowing_and_bad_plugins_are_rejected(monkeypatch, tmp_path):
    bad = ToyExtractor()
    bad.api_version = "9.0"
    _with(monkeypatch, bad)
    with pytest.raises(plugins.PluginError, match="not supported"):
        pipeline.build(_toy_repo(tmp_path), extractors=["toy"])
    weird = ToyExtractor()
    weird.node_kinds = frozenset({"spaceship"})
    _with(monkeypatch, weird)
    with pytest.raises(plugins.PluginError, match="unknown kinds"):
        pipeline.build(_toy_repo(tmp_path), extractors=["toy"])
    _with(monkeypatch, ToyExtractor(), error="shadows a built-in plug-in name; ignored")
    with pytest.raises(plugins.PluginError, match="shadows"):
        pipeline.build(_toy_repo(tmp_path), extractors=["toy"])
    pack = ToyPack()
    pack.attaches_to = ("cobol",)
    _with(monkeypatch, pack)
    with pytest.raises(plugins.PluginError, match="not active"):
        pipeline.build(_toy_repo(tmp_path), extractors=["toy-pack"])


# ---------------------------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------------------------


def test_a_failing_plugin_is_reported_and_skipped_unless_strict(monkeypatch, tmp_path):
    t = ToyExtractor()
    t.mode = "raise"
    _with(monkeypatch, t)
    repo = _toy_repo(tmp_path)
    res = pipeline.build(repo, extractors=["toy"])
    assert res.epoch.attrs["plugin_failures"] == [
        {"error": "RuntimeError: boom", "kind": "extractor", "name": "toy", "version": "1.0.0"}
    ]
    assert "svc/b.py::gamma" in {n.qualified_name for n in res.graph.nodes.values()}  # python still ran
    with pytest.raises(RuntimeError, match="boom"):
        pipeline.build(repo, extractors=["toy"], strict=True)


def test_a_hanging_plugin_times_out(monkeypatch, tmp_path):
    t = ToyExtractor()
    t.mode = "hang"
    _with(monkeypatch, t)
    res = pipeline.build(_toy_repo(tmp_path), extractors=["toy"], plugin_timeout_s=0.2)
    assert "timed out" in res.epoch.attrs["plugin_failures"][0]["error"]


def test_a_failing_pack_hook_leaves_the_extractor_output_untouched(monkeypatch, tmp_path):
    p = ToyPack()
    p.fail = True
    _with(monkeypatch, p)
    res = pipeline.build(_toy_repo(tmp_path), extractors=["toy-pack"])
    assert res.epoch.attrs["plugin_failures"][0]["name"] == "toy-pack"
    assert not any(n.attrs.get("poisoned") for n in res.graph.nodes.values())


def test_file_accessor_contract(tmp_path):
    from ad2v.extract.files import SourceFile

    acc = FileAccessor([SourceFile("a.py", tmp_path / "a.py", "x", ids.content_hash("x"))])
    assert acc.read_text("a.py") == "x" and "a.py" in acc and len(acc) == 1
    with pytest.raises(FileAccessError):
        acc.read_text("b.py")
    assert acc.violations == ["b.py"]


# ---------------------------------------------------------------------------------------------
# parse cache and GC
# ---------------------------------------------------------------------------------------------


def test_parse_cache_key_names_the_extractor_and_survives_prune(tmp_path):
    out = tmp_path / "x.ad2v"
    first = pipeline.extract_to_file(FIXTURE, None, out)
    conn = sqlite3.connect(out)
    vers = {r[0] for r in conn.execute("SELECT DISTINCT extractor_version FROM parse_cache")}
    rhs = {r[0] for r in conn.execute("SELECT DISTINCT rules_hash FROM parse_cache")}
    n = conn.execute("SELECT COUNT(*) FROM parse_cache").fetchone()[0]
    conn.close()
    assert vers == {"python@1.0.0:python-local-3"}
    # the fixture's ad2v.yaml has a rules overlay, so its effective hash differs from the default
    assert rhs == {first.rules["plugins"][0]["effective_rules_hash"]}
    res = pipeline.extract_to_file(
        FIXTURE, None, out, into=True, test_results=[FIXTURE / "test-results" / "junit.xml"]
    )
    assert res.stats["cache_misses"] == 0 and res.stats["cache_hits"] > 0
    admin.prune_file(out, 1, True, False)
    conn = sqlite3.connect(out)
    assert conn.execute("SELECT COUNT(*) FROM parse_cache").fetchone()[0] == n
    conn.close()


# ---------------------------------------------------------------------------------------------
# conformance kit
# ---------------------------------------------------------------------------------------------


def _fixture_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fx"
    write_tree(d, {"svc/a.toy": "def alpha\ndef beta\n"})
    return d


def _ids(result: dict) -> dict[str, bool]:
    return {c["id"]: c["passed"] for c in result["checks"]}


def test_conformance_kit_passes_a_good_plugin(monkeypatch, tmp_path):
    _with(monkeypatch, ToyExtractor())
    r = conformance.check("toy", _fixture_dir(tmp_path))
    assert r["passed"], r
    assert set(_ids(r)) == {
        "api_handshake",
        "runs_clean",
        "determinism",
        "id_stability",
        "schema",
        "file_access",
        "side_effects",
        "declared_kinds",
    }
    assert r["fixture"] == "fx" and str(tmp_path) not in conformance.format_text(r)


@pytest.mark.parametrize(
    "mode,failing",
    [
        ("undeclared", "declared_kinds"),
        ("random", "determinism"),
        ("outside", "file_access"),
        ("raise", "runs_clean"),
    ],
)
def test_conformance_kit_catches_bad_plugins(monkeypatch, tmp_path, mode, failing):
    t = ToyExtractor()
    t.mode = mode
    _with(monkeypatch, t)
    r = conformance.check("toy", _fixture_dir(tmp_path))
    assert not r["passed"] and _ids(r)[failing] is False, r


def test_conformance_kit_audits_real_file_opens(monkeypatch, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s", encoding="utf-8")

    class Sneaky(ToyExtractor):
        def extract(self, ctx):
            secret.read_text(encoding="utf-8")
            return super().extract(ctx)

    _with(monkeypatch, Sneaky())
    r = conformance.check("toy", _fixture_dir(tmp_path))
    fa = next(c for c in r["checks"] if c["id"] == "file_access")
    assert not fa["passed"] and fa["detail"]["opens_outside_file_set"] == ["<outside>/secret.txt"]


def test_conformance_kit_handshake_failure_and_unknown_name(monkeypatch, tmp_path):
    assert conformance.check("nope", tmp_path)["passed"] is False
    t = ToyExtractor()
    t.api_version = "7.1"
    _with(monkeypatch, t)
    r = conformance.check("toy", _fixture_dir(tmp_path))
    assert r["checks"][0]["id"] == "api_handshake" and not r["passed"]


def test_builtins_pass_the_conformance_kit():
    for name in ("python", "python-frameworks"):
        r = conformance.check(name, ROOT / "fixtures" / "sdd-presets" / "spec-kit")
        assert r["passed"], r


# ---------------------------------------------------------------------------------------------
# the out-of-tree examples, loaded from examples/ without installing them
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def examples_on_path(monkeypatch):
    for d in ("routes-dsl-extractor", "bottle-framework-pack"):
        monkeypatch.syspath_prepend(str(EXAMPLES / d / "src"))
    yield
    for m in ("ad2v_routes_dsl", "ad2v_bottle_pack"):
        sys.modules.pop(m, None)


def test_example_routes_dsl_extractor(monkeypatch, tmp_path, examples_on_path):
    from ad2v_routes_dsl import RoutesDslExtractor

    _with(monkeypatch, RoutesDslExtractor())
    fx = EXAMPLES / "routes-dsl-extractor" / "fixture"
    assert conformance.check("routes-dsl", fx)["passed"]
    repo = tmp_path / "orders"
    shutil.copytree(fx, repo)
    res = pipeline.build(repo)  # enabled by the fixture's ad2v.yaml
    routes = sorted(n.qualified_name for n in res.graph.nodes.values() if n.kind == "http_route")
    assert routes == [
        "http:orders:GET /v1/orders",
        "http:orders:GET /v1/orders/{id}",
        "http:orders:POST /v1/orders",
    ]
    statuses = {
        res.graph.nodes[lk.spec_node_id].qualified_name: lk.status
        for lk in res.pairing.links
        if lk.spec_node_id
    }
    assert statuses["POST /v1/orders/{id}/cancel"] == "missing"
    assert statuses["GET /v1/orders"] == "implemented"


def test_example_bottle_pack(monkeypatch, examples_on_path):
    from ad2v_bottle_pack import BottlePack

    _with(monkeypatch, BottlePack())
    fx = EXAMPLES / "bottle-framework-pack" / "fixture"
    assert conformance.check("bottle", fx)["passed"]
    without = pipeline.build(fx)
    with_pack = pipeline.build(fx, extractors=["bottle"])

    def routes(r):
        return sorted(n.name for n in r.graph.nodes.values() if n.kind == "http_route")

    assert routes(without) == [] and routes(with_pack) == ["GET /health", "GET /hello/<name>"]


def test_cli_extractors_list_and_check(capsys, tmp_path):
    from ad2v.cli import main

    assert main(["extractors", "list", "--repo", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "python-frameworks" in out and "built-in" in out
    assert main(["extractors", "list", "--json", "--repo", str(tmp_path)]) == 0
    data = yaml.safe_load(capsys.readouterr().out)
    assert {p["name"] for p in data["plugins"]} >= {"python", "python-frameworks"}
    fx = ROOT / "fixtures" / "sdd-presets" / "kiro"
    assert main(["extractor", "check", "python", "--fixture", str(fx), "--json"]) == 0
    assert '"passed": true' in capsys.readouterr().out


def test_extract_prints_plugin_identity(capsys, tmp_path):
    from ad2v.cli import main

    assert main(["extract", "--repo", str(FIXTURE), "--out", str(tmp_path / "x.ad2v")]) == 0
    out = capsys.readouterr().out
    assert "plug-in: extractor python 1.0.0 (api 1.0, built-in) rules " in out
    assert "plug-in: framework python-frameworks 1.0.0" in out


def test_epoch_rules_record_plugin_identity(tmp_path):
    out = tmp_path / "x.ad2v"
    res = pipeline.extract_to_file(ROOT / "fixtures" / "sdd-presets" / "kiro", None, out)  # no overlay
    conn = store.open_readonly(out)
    stored = store.load_rules(conn, res.epoch.rules_hash)
    conn.close()
    names = [(p["name"], p["version"]) for p in stored["plugins"]]
    assert names == [("python", "1.0.0"), ("python-frameworks", "1.0.0")]
    assert stored["plugins"][0]["effective_rules_hash"].startswith(PRE_P8_RULES_HASH)


@pytest.mark.parametrize("effect", ["network", "process", "write"])
def test_conformance_kit_flags_side_effects(monkeypatch, tmp_path, effect):
    import socket
    import subprocess

    out = tmp_path / "written.txt"

    class Effectful(ToyExtractor):
        def extract(self, ctx):
            if effect == "network":
                with contextlib.suppress(OSError):
                    socket.getaddrinfo("localhost", 80)
            elif effect == "process":
                subprocess.run([sys.executable, "-c", "pass"], check=False)
            else:
                out.write_text("x", encoding="utf-8")
            return super().extract(ctx)

    _with(monkeypatch, Effectful())
    r = conformance.check("toy", _fixture_dir(tmp_path))
    se = next(c for c in r["checks"] if c["id"] == "side_effects")
    assert not se["passed"] and any(x.startswith(effect) for x in se["detail"]), se


def test_conformance_kit_reports_a_missing_fixture_and_formats_failures(monkeypatch, tmp_path):
    _with(monkeypatch, ToyExtractor())
    r = conformance.check("toy", tmp_path / "nope")
    assert not r["passed"] and r["checks"][-1]["id"] == "fixture"
    text = conformance.format_text(r)
    assert "FAIL" in text and "fixture directory not found" in text
    t = ToyExtractor()
    t.mode = "undeclared"
    _with(monkeypatch, t)
    bad = conformance.check("toy", _fixture_dir(tmp_path))
    assert "FAIL declared_kinds" in conformance.format_text(bad).replace("  ", " ")
