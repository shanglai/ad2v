from ad2v.manifest import Config, ContainerDecl

from helpers import edges, node, qnames, run_code


def test_structure_qnames_spans_and_hierarchy(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "pkg/mod.py": """
            class Outer:
                class Inner:
                    def m(self):
                        pass

                @staticmethod
                def s():
                    def helper():
                        return 1
                    return helper()


            async def top():
                return 2
        """,
        },
    )
    assert qnames(g, "class") == ["pkg/mod.py::Outer", "pkg/mod.py::Outer.Inner"]
    assert qnames(g, "function") == [
        "pkg/mod.py::Outer.Inner.m",
        "pkg/mod.py::Outer.s",
        "pkg/mod.py::Outer.s.helper",
        "pkg/mod.py::top",
    ]
    s = node(g, "function", "pkg/mod.py::Outer.s")
    assert (s.span_start_line, s.span_end_line) == (6, 10)  # includes decorator
    assert s.attrs["decorators"] == ["staticmethod"]
    assert node(g, "function", "pkg/mod.py::top").attrs["async"] is True
    helper = node(g, "function", "pkg/mod.py::Outer.s.helper")
    assert helper.parent_id == s.id
    comp = node(g, "component", "pkg")
    assert node(g, "module", "pkg/mod.py").parent_id == comp.id
    assert ("pkg/mod.py::Outer.s", "pkg/mod.py::Outer.s.helper") in edges(g, "calls")


def test_container_inference_and_fallback(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "svc_a/pyproject.toml": "[project]\nname='a'\n",
            "svc_a/app/x.py": "def f():\n    pass\n",
            "svc_b/Dockerfile": "FROM python\n",
            "svc_b/y.py": "def g():\n    pass\n",
            "scripts/tool.py": "def h():\n    pass\n",
        },
    )
    assert qnames(g, "container") == ["container:svc_a", "container:svc_b", "container:sys"]
    assert node(g, "module", "svc_b/y.py").parent_id == node(g, "container", "container:svc_b").id
    assert node(g, "component", "scripts").parent_id == node(g, "container", "container:sys").id
    assert node(g, "container", "container:svc_a").attrs["declared"] is False


def test_manifest_containers_longest_prefix(tmp_path):
    cfg = Config(
        system_name="s",
        containers=[
            ContainerDecl("mono", ("src",)),
            ContainerDecl("special", ("src/special",), replicas=3),
        ],
    )
    g, _ = run_code(tmp_path, {"src/a.py": "x = 1\n", "src/special/b.py": "y = 2\n"}, cfg)
    assert node(g, "module", "src/special/b.py").parent_id == node(g, "container", "container:special").id
    assert node(g, "module", "src/a.py").parent_id == node(g, "container", "container:mono").id
    assert node(g, "container", "container:special").attrs["replicas"] == 3


def test_import_and_call_resolution(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/util.py": """
            def helper():
                return 1

            class Svc:
                def __init__(self):
                    self.x = 1

                def run(self):
                    return self.step()

                def step(self):
                    return helper()
        """,
            "app/sub/__init__.py": "",
            "app/sub/deep.py": """
            from .. import util
            from ..util import helper as h
            from . import sibling

            def go():
                util.helper()
                h()
                sibling.f()
                util.Svc()
                len([])
        """,
            "app/sub/sibling.py": "def f():\n    pass\n",
            "app/main.py": """
            import app.util
            import app.sub.deep as deep

            def main():
                app.util.helper()
                deep.go()
        """,
        },
    )
    calls = edges(g, "calls")
    assert ("app/sub/deep.py::go", "app/util.py::helper") in calls
    assert ("app/sub/deep.py::go", "app/sub/sibling.py::f") in calls
    assert ("app/sub/deep.py::go", "app/util.py::Svc.__init__") in calls
    assert ("app/util.py::Svc.run", "app/util.py::Svc.step") in calls
    assert ("app/util.py::Svc.step", "app/util.py::helper") in calls
    assert ("app/main.py::main", "app/util.py::helper") in calls
    assert ("app/main.py::main", "app/sub/deep.py::go") in calls
    g_go = [
        e
        for (s, k, d), e in g.edges.items()
        if k == "calls" and g.nodes[s].name == "go" and g.nodes[d].name == "helper"
    ]
    assert g_go[0].weight == 2
    imports = edges(g, "imports")
    assert ("app/sub/deep.py", "app/util.py") in imports
    assert ("app/sub/deep.py", "app/sub/sibling.py") in imports
    assert ("app/main.py", "app/sub/deep.py") in imports


def test_resources_naming_and_access(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "r.py": """
            import os
            import boto3
            import requests
            import anthropic
            from google.cloud import bigquery, pubsub_v1
            from sqlalchemy import create_engine, text, insert

            DB = "postgresql://user:secret@db.internal:5432/ledger?sslmode=require"
            engine = create_engine(DB)
            bq = bigquery.Client()
            sqs = boto3.client("sqs")
            pub = pubsub_v1.PublisherClient()
            llm = anthropic.Anthropic()

            def a():
                with engine.connect() as conn:
                    conn.execute(text("select 1"))
                    conn.execute(insert(t))
                    conn.execute(some_query)

            def b():
                requests.get("https://api.example.com:8443/v1/x?token=abc")
                bq.query("SELECT 1")
                sqs.send_message(QueueUrl="q", MessageBody="m")
                pub.publish("projects/p/topics/t", b"x")
                llm.messages.create(model="claude-x", max_tokens=5, messages=[])

            def c(client: bigquery.Client):
                client.insert_rows_json("t", [])
        """,
        },
    )
    assert qnames(g, "datastore") == [
        "datastore:google.cloud.bigquery:unknown",
        "datastore:postgresql://db.internal:5432/ledger",
    ]
    assert "secret" not in str([n.attrs for n in g.nodes.values()])
    assert qnames(g, "external_service") == ["external_service:https://api.example.com:8443"]
    assert qnames(g, "queue") == ["queue:boto3.sqs:unknown", "queue:projects/p/topics/t"]
    assert qnames(g, "llm_endpoint") == ["llm_endpoint:claude-x"]
    db = "datastore:postgresql://db.internal:5432/ledger"
    a_edges = {
        (k, g.nodes[d].qualified_name): e for (s, k, d), e in g.edges.items() if g.nodes[s].name == "a"
    }
    assert a_edges[("reads", db)].weight == 2  # select + unknown query (default)
    assert a_edges[("reads", db)].attrs.get("access") == "default"
    assert ("writes", db) in a_edges
    assert ("r.py::c", "datastore:google.cloud.bigquery:unknown") in edges(g, "writes")
    assert ("r.py::b", "queue:boto3.sqs:unknown") in edges(g, "publishes")
    assert ("r.py::b", "llm_endpoint:claude-x") in edges(g, "invokes_llm")


def test_env_var_names_follow_constants(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "cfg.py": 'import os\nURL = os.getenv("SVC_URL")\n',
            "c.py": """
            import httpx
            from cfg import URL
            client = httpx.Client(base_url=URL)

            def f():
                client.post("/x")
        """,
        },
    )
    assert qnames(g, "external_service") == ["external_service:env:SVC_URL"]


def test_behaviors_risks(tmp_path):
    files = {
        "b.py": """
            import asyncio
            import litellm
            import httpx
            from concurrent.futures import ThreadPoolExecutor
            from tenacity import retry, stop_after_attempt
            from sqlalchemy import create_engine, text

            engine = create_engine("sqlite:///x.db")

            def get_one(i):
                with engine.connect() as c:
                    return c.execute(text("SELECT 1"))

            def n_plus_one(items):
                for i in items:
                    get_one(i)

            def nested(groups):
                for g in groups:
                    for i in g:
                        get_one(i)

            def llm_loop(xs):
                return [litellm.completion(model="m", messages=[x]) for x in xs]

            def pure_loop(xs):
                total = 0
                for x in xs:
                    total += x
                return total

            @retry
            def forever():
                pass

            @retry(stop=stop_after_attempt(3))
            def bounded():
                pass

            async def fan(xs):
                await asyncio.gather(*[get_one(x) for x in xs])

            async def fixed():
                await asyncio.gather(get_one(1), get_one(2))

            def pool(xs):
                with ThreadPoolExecutor() as ex:
                    list(ex.map(get_one, xs))

            def tx():
                with engine.begin() as conn:
                    conn.execute(text("UPDATE t SET x = 1"))
                    httpx.post("https://hooks.example.com/notify")
        """,
    }
    g, facts = run_code(tmp_path, files)
    risk = {n.qualified_name: n.attrs["risk"] for n in g.nodes.values() if "risk" in n.attrs}
    assert risk == {
        "b.py::n_plus_one@loop#1": ["io_in_loop"],
        "b.py::nested@loop#1": ["io_in_loop", "nested_loop_io"],
        "b.py::nested@loop#2": ["io_in_loop"],
        "b.py::llm_loop@loop#1": ["llm_in_loop"],
        "b.py::llm_loop@llm_call#1": ["llm_in_loop"],
        "b.py::forever@retry#1": ["unbounded_retry"],
        "b.py::fan@fan_out#1": ["fan_out"],
        "b.py::pool@fan_out#1": ["fan_out"],
        "b.py::tx@transaction#1": ["slow_io_in_transaction"],
    }
    assert node(g, "loop", "b.py::nested@loop#2").parent_id == node(g, "loop", "b.py::nested@loop#1").id
    assert facts.wrappers[node(g, "function", "b.py::forever").id] == [
        node(g, "retry", "b.py::forever@retry#1").id
    ]
    # the parallel event of a fan-out carries the fan_out node
    fan_events = facts.events[node(g, "function", "b.py::fan").id]
    assert fan_events[0].targets == (node(g, "function", "b.py::get_one").id,)
    assert fan_events[0].behaviors == (node(g, "fan_out", "b.py::fan@fan_out#1").id,)


def test_emit_all_keeps_ordinals_stable(tmp_path):
    src = {
        "e.py": """
            import asyncio

            def f(xs):
                for x in xs:
                    pass
                for y in xs:
                    print(y)

            async def g():
                await asyncio.gather(h(), h())

            async def h():
                pass
        """,
    }
    g0, _ = run_code(tmp_path / "a", src)
    assert qnames(g0, "loop") == [] and qnames(g0, "fan_out") == []
    g1, _ = run_code(tmp_path / "b", src, Config(behavior_emit_all=True))
    assert qnames(g1, "loop") == ["e.py::f@loop#1", "e.py::f@loop#2"]
    assert qnames(g1, "fan_out") == ["e.py::g@fan_out#1"]
    assert node(g1, "fan_out", "e.py::g@fan_out#1").attrs["risk"] == []


def test_ports(tmp_path):
    g, facts = run_code(
        tmp_path,
        {
            "web/api.py": """
            from fastapi import APIRouter, FastAPI
            from flask import Blueprint, Flask

            app = FastAPI()
            router = APIRouter(prefix="/items")
            app.include_router(router, prefix="/v2")

            @router.get("/{item_id}")
            def read_item(item_id: int):
                return item_id

            @app.post("/ping")
            async def ping():
                return "pong"

            fl = Flask(__name__)
            bp = Blueprint("bp", __name__, url_prefix="/bp")

            @fl.route("/legacy", methods=["GET", "POST"])
            def legacy():
                pass

            @bp.route("/thing")
            def thing():
                pass
        """,
            "tools/server.py": """
            from mcp.server.fastmcp import FastMCP
            import typer
            import click

            mcp = FastMCP("x")
            cli = typer.Typer()

            @mcp.tool()
            def summarize(x: str) -> str:
                return x

            @mcp.tool(name="renamed_tool")
            def other():
                pass

            @cli.command()
            def do_thing():
                pass

            @click.group()
            def grp():
                pass

            @grp.command("sub-cmd")
            def sub():
                pass
        """,
            "tools/consumer.py": """
            from google.cloud import pubsub_v1
            sub = pubsub_v1.SubscriberClient()

            def on_msg(m):
                m.ack()

            def main():
                sub.subscribe("projects/p/subscriptions/s", on_msg)
        """,
        },
    )
    assert qnames(g, "http_route") == [
        "http:sys:GET /bp/thing",
        "http:sys:GET /legacy",
        "http:sys:GET /v2/items/{item_id}",
        "http:sys:POST /legacy",
        "http:sys:POST /ping",
    ]
    assert qnames(g, "mcp_tool") == ["mcp:sys:renamed_tool", "mcp:sys:summarize"]
    assert qnames(g, "cli_command") == ["cli:sys:do-thing", "cli:sys:grp", "cli:sys:sub-cmd"]
    ev = node(g, "event_consumer", "event:sys:tools/consumer.py::on_msg")
    assert ev.attrs["source"] == "projects/p/subscriptions/s"
    route = node(g, "http_route", "http:sys:GET /v2/items/{item_id}")
    assert route.attrs["handler"] == "web/api.py::read_item"
    assert ("container:sys", route.qualified_name) in edges(g, "exposes")
    assert (route.qualified_name, "web/api.py::read_item") in edges(g, "calls")
    assert len(facts.entry_ports) == 11


def test_explicit_spec_refs(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "m.py": '''
            """Module docstring.

            ad2v: CMP-001
            """
            # ad2v: REQ-001, REQ-002
            @decorator
            def above():
                pass

            def inside():
                # ad2v: REQ-003
                pass

            def trailing():  # ad2v: REQ-004
                pass

            def doc():
                """Does things.

                ad2v: REQ-005
                """

            # ad2v: REQ-009

            x = 1
        ''',
            "tests/test_x.py": """
            def test_req_012_and_cmp_3_behaviour():
                pass

            def test_step_1():
                pass
        """,
        },
    )
    assert node(g, "function", "m.py::above").spec_ref == ["REQ-001", "REQ-002"]
    assert node(g, "function", "m.py::inside").spec_ref == ["REQ-003"]
    assert node(g, "function", "m.py::trailing").spec_ref == ["REQ-004"]
    assert node(g, "function", "m.py::doc").spec_ref == ["REQ-005"]
    assert node(g, "module", "m.py").spec_ref == ["CMP-001", "REQ-009"]
    t = node(g, "function", "tests/test_x.py::test_req_012_and_cmp_3_behaviour")
    assert t.spec_ref == ["CMP-3", "REQ-012"] and t.attrs["is_test"]
    assert node(g, "function", "tests/test_x.py::test_step_1").spec_ref == []


def test_never_executes_repo_code(tmp_path):
    sentinel = tmp_path / "PWNED"
    run_code(
        tmp_path / "repo",
        {
            "evil.py": f'open(r"{sentinel}", "w").write("x")\nimport os\nos.system("echo pwned")\n',
        },
    )
    assert not sentinel.exists()


def test_crlf_and_bom_are_equivalent(tmp_path):
    src = "import os\n\ndef f():\n    for x in y:\n        os.getenv('A')\n"
    g1, _ = run_code(tmp_path / "a", {"m.py": src})
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "m.py").write_bytes(b"\xef\xbb\xbf" + src.replace("\n", "\r\n").encode())
    g2, _ = run_code(tmp_path / "b", {})
    assert {k: (n.content_hash, n.span_start_line, n.span_end_line) for k, n in g1.nodes.items()} == {
        k: (n.content_hash, n.span_start_line, n.span_end_line) for k, n in g2.nodes.items()
    }


def test_syntax_errors_do_not_crash(tmp_path):
    g, _ = run_code(tmp_path, {"bad.py": "def f(:\n    pass\n\ndef g():\n    return 1\n"})
    assert "bad.py::g" in qnames(g, "function")


def test_datastore_library_helpers_are_not_io(tmp_path):
    g, _ = run_code(
        tmp_path,
        {
            "h.py": """
                from sqlalchemy import inspect
                import requests

                def cols(entities):
                    return [inspect(e).columns for e in entities]

                def fetch(urls):
                    return [requests.get(u) for u in urls]
            """,
        },
    )
    risk = {n.qualified_name: n.attrs["risk"] for n in g.nodes.values() if "risk" in n.attrs}
    assert risk == {"h.py::fetch@loop#1": ["io_in_loop"]}
    assert qnames(g, "datastore") == []
