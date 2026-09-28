"""P3 unit tests: orphan policy, entry-point recognizers, parse-cache equivalence, lineage edge cases."""

import pytest

from ad2v import history, ids, ir, pipeline
from ad2v.extract.code.python_local import find_node, parse_refs
from ad2v.manifest import ManifestError, load

from helpers import FIXTURE, node, qnames, run_code, write_tree

APP = """
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def items():
    return []
"""


# --- orphan policy (P2 issue 18) ------------------------------------------------------------


def _statuses(res):
    return {res.graph.nodes[n].qualified_name: s.status for n, s in res.pairing.statuses.items()}


def test_orphan_policy_auto_without_specs(tmp_path):
    write_tree(tmp_path, {"svc/pyproject.toml": "", "svc/web.py": APP})
    res = pipeline.build(tmp_path)
    st = _statuses(res)
    assert "orphan" not in st.values()
    assert st["http:svc:GET /items"] == "none"
    assert res.meta["spec_coverage"] == "none" and res.epoch.attrs["orphan_policy"] == "auto"


def test_orphan_policy_strict_and_off(tmp_path):
    write_tree(
        tmp_path / "strict",
        {"ad2v.yaml": "pairing: {orphan_policy: strict}\n", "svc/pyproject.toml": "", "svc/web.py": APP},
    )
    assert _statuses(pipeline.build(tmp_path / "strict"))["http:svc:GET /items"] == "orphan"  # P2 behavior
    files = {
        "ad2v.yaml": "pairing: {orphan_policy: off}\n",
        "svc/pyproject.toml": "",
        "svc/web.py": APP,
        "specs/s.md": "- [REQ-1] The svc shall list items.\n",
    }
    write_tree(tmp_path / "off", files)
    res = pipeline.build(tmp_path / "off", tmp_path / "off" / "specs")
    assert "orphan" not in _statuses(res).values() and res.meta["spec_coverage"] == "present"
    write_tree(tmp_path / "auto", {**files, "ad2v.yaml": "system: {name: x}\n"})
    res = pipeline.build(tmp_path / "auto", tmp_path / "auto" / "specs")
    assert _statuses(res)["http:svc:GET /items"] == "orphan"  # with specs, auto behaves like strict


def test_orphan_policy_is_part_of_config_hash(tmp_path):
    write_tree(tmp_path / "a", {"ad2v.yaml": "pairing: {orphan_policy: strict}\n"})
    write_tree(tmp_path / "b", {"ad2v.yaml": "pairing: {orphan_policy: off}\n"})
    a, b = load(tmp_path / "a"), load(tmp_path / "b")
    assert a.config_hash != b.config_hash
    assert load(tmp_path / "missing").config_json == {"effective": {"orphan_policy": "auto"}, "manifest": {}}
    write_tree(tmp_path / "bad", {"ad2v.yaml": "pairing: {orphan_policy: sometimes}\n"})
    with pytest.raises(ManifestError):
        load(tmp_path / "bad")


# --- entry-point recognizers (P2 issue 17) -----------------------------------------------------


def _ports(g, kind):
    return {n.qualified_name: n.attrs for n in g.nodes.values() if n.kind == kind}


def test_main_block(tmp_path):
    g, facts = run_code(
        tmp_path,
        {
            "tool.py": "def run():\n    pass\n\nif __name__ == '__main__':\n    run()\n",
            "lib.py": "if '__main__' == __name__:\n    pass\n",
        },
    )
    ports = _ports(g, "cli_command")
    assert ports["cli:sys:__main__:tool.py"]["trigger"] == "main"
    assert ports["cli:sys:__main__:tool.py"]["handler"] == "tool.py"
    assert "cli:sys:__main__:lib.py" in ports
    port = node(g, "cli_command", "cli:sys:__main__:tool.py")
    assert (port.span_start_line, port.span_end_line) == (4, 5)
    assert (port.id, node(g, "module", "tool.py").id) in facts.entry_ports


def test_celery_tasks_and_beat(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "proj/__init__.py": "",
            "proj/tasks.py": """
            from celery import Celery, shared_task
            app = Celery("proj")

            @app.task
            def nightly():
                pass

            @app.task(bind=True)
            def with_opts(self):
                pass

            @shared_task
            def cleanup():
                pass

            app.conf.beat_schedule = {
                "every-night": {"task": "proj.tasks.nightly", "schedule": 3600},
                "missing": {"task": "proj.tasks.does_not_exist", "schedule": 60},
            }
        """,
        },
    )
    ports = _ports(g, "event_consumer")
    assert ports["event:sys:celery_task:proj/tasks.py::nightly"]["trigger"] == "celery_task"
    assert "event:sys:celery_task:proj/tasks.py::with_opts" in ports
    assert "event:sys:celery_task:proj/tasks.py::cleanup" in ports
    beat = ports["event:sys:celery_beat:proj/tasks.py::nightly"]
    assert beat["trigger"] == "celery_beat" and beat["schedule_name"] == "every-night"


def test_apscheduler_and_schedule(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "jobs.py": """
            import schedule
            from apscheduler.schedulers.background import BackgroundScheduler

            sched = BackgroundScheduler()

            def sync():
                pass

            def report():
                pass

            @sched.scheduled_job("cron", hour=1)
            def purge():
                pass

            def main():
                sched.add_job(sync, "interval", minutes=5)
                sched.add_job(func=report, trigger="cron")
                schedule.every(10).minutes.do(report)
        """,
        },
    )
    ports = _ports(g, "event_consumer")
    assert ports["event:sys:apscheduler:jobs.py::sync"]["trigger"] == "apscheduler"
    assert "event:sys:apscheduler:jobs.py::report" in ports
    assert "event:sys:apscheduler:jobs.py::purge" in ports
    assert ports["event:sys:schedule:jobs.py::report"]["trigger"] == "schedule"


def test_click_nested_groups(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "cli.py": """
            import click

            @click.group()
            def root():
                pass

            @root.group()
            def db():
                pass

            @db.command("migrate")
            def migrate():
                pass

            @root.group(name="cache")
            def cache_group():
                pass

            @db.command("list")
            def list_tables():
                pass

            @cache_group.command("list")
            def list_keys():
                pass

            @root.command()
            def serve():
                pass
        """,
        },
    )
    ports = _ports(g, "cli_command")
    migrate = ports["cli:sys:db migrate"]
    assert migrate["trigger"] == "click" and migrate["group"] == "cli.py::db"
    assert ports["cli:sys:serve"]["trigger"] == "click"
    # same command name under two nested groups: the group path keeps the ports apart (ADR-0021)
    assert ports["cli:sys:db list"]["handler"] == "cli.py::list_tables"
    assert ports["cli:sys:cache list"]["handler"] == "cli.py::list_keys"
    assert qnames(g, "cli_command") == [
        "cli:sys:cache",
        "cli:sys:cache list",
        "cli:sys:db",
        "cli:sys:db list",
        "cli:sys:db migrate",
        "cli:sys:root",
        "cli:sys:serve",
    ]


def test_entry_points_raise_reach(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "worker.py": """
            import requests

            def run(urls):
                for u in urls:
                    requests.get(u)

            if __name__ == "__main__":
                run([])
        """,
        },
    )
    from ad2v import severity, workflows
    from ad2v.manifest import Config

    _, facts = run_code(tmp_path, {})  # reuse the same tree: rebuild facts
    wfs = workflows.build_all(g, facts, Config())
    ranked = severity.apply(g, wfs, {"severity": {"base": {"io_in_loop": 3}, "reach": {"reachable": 1.5}}})
    loop = g.nodes[ranked[0]]
    assert loop.kind == "loop" and loop.attrs["severity_reach"] == 1 and loop.attrs["severity"] == 4.5


# --- parse cache -------------------------------------------------------------------------------


def _graph_payload(g):
    """Every node and edge, normative payload plus volatile lines, as comparable strings."""
    from ad2v import ids, store

    nodes = sorted(
        ids.canonical_json([store.node_payload(n), n.span_start_line, n.span_end_line])
        for n in g.nodes.values()
    )
    edges = sorted(
        ids.canonical_json([store.edge_payload(e), e.attrs.get("lines")]) for e in g.edges.values()
    )
    return nodes, edges


def test_cached_extraction_equals_uncached():
    cold = pipeline.build(FIXTURE, FIXTURE / "specs")
    cache = {(p, h): lf for p, (h, lf) in cold.cache_entries.items()}
    warm = pipeline.build(FIXTURE, FIXTURE / "specs", cache_loader=lambda _rules_hash: cache)
    assert warm.stats["cache_hits"] == warm.stats["files_code"] and warm.stats["cache_misses"] == 0
    assert _graph_payload(warm.graph) == _graph_payload(cold.graph)
    assert warm.epoch.epoch_id == cold.epoch.epoch_id


def test_stale_cache_version_is_ignored():
    cold = pipeline.build(FIXTURE, FIXTURE / "specs")
    cache = {(p, h): {**lf, "v": "python-local-0"} for p, (h, lf) in cold.cache_entries.items()}
    warm = pipeline.build(FIXTURE, FIXTURE / "specs", cache_loader=lambda _rules_hash: cache)
    assert warm.stats["cache_hits"] == 0


def test_parse_refs_and_find_node():
    assert parse_refs("REQ-1, REQ-2@1a2b3c4d CMP-3@nothex") == [
        ["REQ-1", None],
        ["REQ-2", "1a2b3c4d"],
        ["CMP-3", None],
    ]
    import tree_sitter_python as tsp
    from tree_sitter import Language, Parser

    root = Parser(Language(tsp.language())).parse(b"x = f(1)\n").root_node
    call = root.named_children[0].named_children[0].child_by_field_name("right")
    assert find_node(root, [call.start_byte, call.end_byte], "call").type == "call"
    with pytest.raises(LookupError):
        find_node(root, [0, 1], "class_definition")


# --- lineage edge cases --------------------------------------------------------------------------


def _g(nodes):
    g = ir.Graph()
    for kind, qname, attrs, content in nodes:
        g.nodes[ids.node_id("code", kind, qname)] = ir.Node(
            "code", kind, qname, qname, attrs=attrs, content_hash=content
        )
    return g


def test_anchored_header_threshold_and_ties():
    parent = _g(
        [
            ("loop", "m.py::f@loop#aaaa", {"header": "orders"}, "c1"),
            ("loop", "m.py::f@loop#bbbb", {"header": "user_ids"}, "c2"),
        ]
    )
    child = _g(
        [
            ("loop", "m.py::f@loop#cccc", {"header": "orders[:]"}, "c3"),  # same tokens -> 1.0
            ("loop", "m.py::f@loop#dddd", {"header": "user_names"}, "c4"),  # {user,names} vs {user,ids}: 0.33
        ]
    )
    lin = history.compute_lineage(parent, child)
    assert [(r[2], r[3]) for r in lin.rows] == [("anchored_header", 1.0)]
    # a tie between two candidates is never guessed: it becomes `ambiguous` + needs_review evidence
    parent = _g([("loop", "m.py::f@loop#aaaa", {"header": "a b"}, "c1")])
    child = _g(
        [
            ("loop", "m.py::f@loop#cccc", {"header": "a b c"}, "c3"),
            ("loop", "m.py::f@loop#dddd", {"header": "a b d"}, "c4"),
        ]
    )
    lin = history.compute_lineage(parent, child)
    assert {r[2] for r in lin.rows} == {"ambiguous"} and lin.forward == {}
    assert set(lin.ambiguous_reasons()) == {
        ids.node_id("code", "loop", "m.py::f@loop#cccc"),
        ids.node_id("code", "loop", "m.py::f@loop#dddd"),
    }


def test_same_route_lineage():
    def route(qname, path):
        return ("http_route", qname, {"method": "GET", "path": path}, "h-" + qname)

    parent = _g([route("http:api:GET /runs/{id}", "/runs/{id}")])
    child = _g([route("http:api:GET /runs/{run_id}", "/runs/{run_id}")])
    lin = history.compute_lineage(parent, child)
    assert [r[2] for r in lin.rows] == ["same_route"]


def test_same_content_needs_a_unique_match():
    parent = _g(
        [("function", "a.py::f", {"body_hash": "x"}, "1"), ("function", "a.py::g", {"body_hash": "x"}, "2")]
    )
    child = _g([("function", "a.py::h", {"body_hash": "x"}, "3")])
    assert history.compute_lineage(parent, child).rows == []  # two candidates: no guess
    assert history.jaccard("", "") == 1.0


def test_port_with_two_handlers_round_trips(tmp_path):
    from ad2v import store

    src = APP + '\n@app.get("/items")\ndef items_again():\n    return []\n'
    repo = tmp_path / "repo"
    write_tree(repo, {"app.py": src})
    out = tmp_path / "x.ad2v"
    res = pipeline.extract_to_file(repo, None, out)
    ports = [p for p, _ in res.facts.entry_ports]
    assert len(ports) == 2 and len(set(ports)) == 1
    conn = store.open_readonly(out)
    try:
        assert store.load_code_facts(conn, store.head_epoch(conn)).entry_ports == sorted(
            res.facts.entry_ports
        )
    finally:
        conn.close()
    wfs = [w for w in res.workflows if w.entry_node_id == ports[0]]
    assert len(wfs) == 1 and len(wfs[0].steps[1].node_ids) == 2


def test_function_local_import_shadows_module_def(tmp_path):
    # dispatch's cli.py: a click command `install_plugins` and other commands doing
    # `from ...utils.cli import install_plugins` inside their bodies (found by the P3 top-10 review)
    g, _ = run_code(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/util.py": "def run():\n    pass\n",
            "pkg/cli.py": """
            def run():
                pass

            def other():
                from pkg.util import run
                run()

            def relative():
                from .util import run as go
                go()

            def plain():
                run()
        """,
        },
    )
    calls = {
        (g.nodes[e.src].qualified_name, g.nodes[e.dst].qualified_name)
        for e in g.edges.values()
        if e.kind == "calls"
    }
    assert ("pkg/cli.py::other", "pkg/util.py::run") in calls
    assert ("pkg/cli.py::other", "pkg/cli.py::run") not in calls
    assert ("pkg/cli.py::relative", "pkg/util.py::run") in calls
    assert ("pkg/cli.py::plain", "pkg/cli.py::run") in calls  # module scope is unaffected
