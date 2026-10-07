"""P8.1 (ADR-0066): code in a language no active extractor reads is `not_evaluable`, never a false
`specified`, `missing` or `orphan`."""

from __future__ import annotations

import shutil
from pathlib import Path

from ad2v import ir, pipeline, plugins, scope
from ad2v.api import API_VERSION, CodeFacts, ExtractOutput

from helpers import write_tree

POLY = Path(__file__).resolve().parent.parent / "fixtures" / "polyglot"


def _status(res: pipeline.Result) -> dict[str, str]:
    g = res.graph
    return {g.nodes[nid].qualified_name: st.status for nid, st in res.pairing.statuses.items()}


def test_polyglot_fixture_statuses():
    res = pipeline.build(POLY)
    st = _status(res)
    assert st["REQ-001"] == "implemented"  # Python: evaluated
    assert st["REQ-002"] == "not_evaluable"  # annotated in TypeScript
    assert st["REQ-003"] == "not_evaluable"  # P9 (issue 95): its component maps to TypeScript-only code
    assert st["REQ-004"] == "not_evaluable"  # P9: named only by a TypeScript test title
    assert st["CMP-002"] == "not_evaluable"  # mapped to a container that is all TypeScript
    assert st["web/src/cart.ts"] == st["web/src/format.ts"] == "not_evaluable"
    assert st["container:web"] == st["web/src"] == "not_evaluable"  # not orphans
    assert "orphan" not in st.values()
    mods = {n.path: n for n in res.graph.nodes.values() if n.kind == "module"}
    assert set(mods) == {"api/app/main.py", "web/src/cart.ts", "web/src/cart.test.ts", "web/src/format.ts"}
    assert mods["web/src/cart.ts"].attrs == {
        "extracted": False,
        "language": "typescript",
        "spec_ref_sources": {"REQ-002": ["comment"]},
    }
    assert res.stats["unextracted"] == {"typescript": 3}
    ev = next(lk for lk in res.pairing.links if lk.status == "not_evaluable" and lk.spec_node_id)
    assert {"kind": "language_out_of_scope", "languages": ["typescript"]} in ev.evidence
    assert res.rules["scope"]["version"] == scope.SCOPE_VERSION


def test_unextracted_files_are_epoch_inputs(tmp_path):
    repo = tmp_path / "polyglot"
    shutil.copytree(POLY, repo)
    a = pipeline.build(repo)
    (repo / "web" / "src" / "format.ts").write_text("export const x = 1;\n", encoding="utf-8")
    b = pipeline.build(repo)
    assert a.epoch.repo_tree_hash != b.epoch.repo_tree_hash and a.epoch.epoch_id != b.epoch.epoch_id


def test_comment_markers_in_many_syntaxes():
    text = (
        "// ad2v: REQ-001\n"
        "/* ad2v: REQ-002, REQ-003 */\n"
        "  * ad2v: REQ-004\n"
        "# ad2v: REQ-005\n"
        "-- ad2v: REQ-006\n"
        "<!-- ad2v: REQ-007 -->\n"
        'const s = "ad2v: REQ-999";\n'  # not a comment: ignored
    )
    assert [r for r, _ in scope.refs(text)] == [f"REQ-00{i}" for i in range(1, 8)]
    assert scope.language("a/b.tsx") == "typescript" and scope.language("x.d.ts") is None
    assert scope.language("README.md") is None and scope.language("Main.java") == "java"


def test_mixed_component_stays_evaluable(tmp_path):
    """A component with Python and TypeScript is judged on its Python: no blanket not_evaluable."""
    write_tree(
        tmp_path / "mix",
        {
            "svc/pyproject.toml": "[project]\nname='s'\n",
            "svc/core/a.py": "def f():\n    return 1\n",
            "svc/core/b.ts": "export const b = 1;\n",
            "specs/s.md": "# S\n\n## Component: Core {#CMP-001}\n\n- [REQ-001] The core shall f.\n",
            "ad2v.yaml": "pairing:\n  components: {CMP-001: svc}\n",
        },
    )
    st = _status(pipeline.build(tmp_path / "mix"))
    assert st["CMP-001"] == "implemented"
    assert st["svc/core/b.ts"] == "not_evaluable"
    assert st["svc/core"] != "not_evaluable"


class TsExtractor:
    api_version = API_VERSION
    name = "toy-ts"
    version = "0.0.1"
    languages = ("typescript",)
    file_patterns = ("*.ts",)
    rules_files: tuple[Path, ...] = ()
    node_kinds = frozenset({"module"})
    edge_kinds: frozenset[str] = frozenset()

    def extract(self, ctx):
        facts = CodeFacts()
        for f in ctx.files:
            facts.files_read[f.path] = f.content_hash
            ctx.graph.add_node(
                ir.Node(
                    "code",
                    "module",
                    f.path,
                    f.path,
                    parent_id=ctx.layout.parent_for_module(f.path),
                    path=f.path,
                    content_hash=f.content_hash,
                    attrs={"language": "typescript"},
                    spec_ref=[r for r, _ in scope.refs(f.text)],
                )
            )
        return ExtractOutput(facts=facts)


def test_an_extractor_for_the_language_makes_it_evaluable(monkeypatch):
    base = [d for d in plugins.discover() if d.builtin]
    ts = plugins.Discovered("extractor", "toy-ts", False, "t", "1", "t:t", TsExtractor)
    monkeypatch.setattr(plugins, "discover", lambda: [*base, ts])
    st = _status(pipeline.build(POLY, extractors=["toy-ts"]))
    assert st["REQ-002"] == "implemented"
    assert "not_evaluable" not in st.values()


def test_issue_95_evidence_on_the_polyglot_fixture():
    res = pipeline.build(POLY)
    g = res.graph
    ev = {
        g.nodes[lk.spec_node_id].qualified_name: [e["kind"] for e in lk.evidence]
        for lk in res.pairing.links
        if lk.spec_node_id
    }
    assert ev["REQ-003"] == ["component_out_of_scope"]
    assert ev["REQ-004"] == ["annotation", "language_out_of_scope", "test_in_unread_language"]
    t = next(n for n in g.nodes.values() if n.qualified_name == "web/src/cart.test.ts")
    assert t.attrs["spec_ref_sources"] == {"REQ-004": ["test_title"]}


def test_test_titles_in_many_languages_are_references_never_run():
    text = (
        'it("RF-001 concilia", () => {})\n'
        "test('muestra RF-002 y RF-003', () => {})\n"
        "describe(`HU-001`, () => {})\n"
        '@DisplayName("RF-004 exporta")\n'
        "fun `RF-005 reintenta`() {}\n"
        "func TestRF006Concilia(t *testing.T) {}\n"
        "func TestHU010_2(t *testing.T) {}\n"
        'const x = "RF-999"\n'
    )
    assert [r for r, _ in scope.test_refs(text)] == [
        "RF-001",
        "RF-002",
        "RF-003",
        "HU-001",
        "RF-004",
        "RF-005",
        "RF-006",
        "HU-010.2",
    ]


def test_tests_in_unread_languages_never_verify(tmp_path):
    write_tree(
        tmp_path / "w",
        {
            "web/package.json": "{}",
            "web/a.test.ts": 'it("REQ-001 works", () => {})\n',
            "specs/s.md": "# S\n\n## Component: Web {#CMP-001}\n\n- [REQ-001] The web shall work.\n",
            "junit.xml": '<testsuite><testcase classname="web.a" name="REQ-001 works"/></testsuite>',
        },
    )
    res = pipeline.build(tmp_path / "w", test_results=[tmp_path / "w" / "junit.xml"])
    assert _status(res)["REQ-001"] == "not_evaluable"


def test_default_excludes_and_migrations(tmp_path):
    files = {
        "app.py": "x = 1\n",
        "web/src/ok.ts": "export const ok = 1;\n",
        "db/migrations/0001_init.py": "x = 1\n",
        "db/migrations/0001_init.sql": "CREATE TABLE t (id INTEGER PRIMARY KEY);\n",
        "alembic/versions/a.py": "x = 1\n",
        ".venv-x/lib/site.py": "x = 1\n",
    }
    for d in ("node_modules/lib", "dist", ".next", "out", "coverage", "vendor"):
        files[f"web/{d}/x.js"] = "x\n"
    files["web/target/G.java"] = "class G {}\n"
    files["web/src/h.min.js"] = "x\n"
    files["web/src/h.js.map"] = "{}\n"
    write_tree(tmp_path / "x", files)
    res = pipeline.build(tmp_path / "x")
    mods = sorted(n.path for n in res.graph.nodes.values() if n.kind == "module")
    assert mods == ["app.py", "web/src/ok.ts"]
    from ad2v.extract import files as filewalk
    from ad2v.manifest import DEFAULT_EXCLUDES, code_excluded

    walked = filewalk.walk(tmp_path / "x", DEFAULT_EXCLUDES)
    assert "db/migrations/0001_init.sql" in walked and not code_excluded("db/migrations/0001_init.sql")
    assert code_excluded("db/migrations/0001_init.py") and code_excluded("alembic/versions/a.py")
    sql_gone = pipeline.build(tmp_path / "x")
    (tmp_path / "x" / "db" / "migrations" / "0001_init.sql").write_text("CREATE TABLE u (id INT);\n")
    assert (
        pipeline.build(tmp_path / "x").epoch.repo_tree_hash != sql_gone.epoch.repo_tree_hash
    )  # SQL is an input
