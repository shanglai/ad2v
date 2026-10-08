# ruff: noqa: E501  (inline .tf and plan fixtures)
"""P10: the infra layer (plan JSON, static .tf), secrets policy, the env-var bridge, the C4 view."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from ad2v import c4, dump, ids, ir, pipeline, store
from ad2v.cli import main
from ad2v.infra import InfraInputError, bridge, envreads, model, parse_plan_args, plan, static
from ad2v.manifest import from_data
from ad2v.validate import validate

from helpers import FIXTURE, write_tree

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "fixtures" / "infra"
BF = ROOT / "fixtures" / "brownfield-es"


def _read(p: Path, env: str = "prod") -> plan.PlanRead:
    return plan.read(plan.load_json(p.read_bytes()), env)


def _by_addr(r) -> dict[str, model.Resource]:
    return {x.address: x for x in r.resources}


# -- plan JSON ------------------------------------------------------------------------------------
def test_gcp_plan_modules_for_each_env_sources_actions():
    r = _read(INFRA / "gcp" / "plan.json")
    assert r.format_version == "1.2"
    res = _by_addr(r)
    api = res['module.services["api"].google_cloud_run_v2_service.this']
    assert api.kind == "deployment_unit" and api.base == "module.services.google_cloud_run_v2_service.this"
    assert api.module == 'module.services["api"]' and api.action == "update"
    assert {k: v.to_dict() for k, v in api.env_vars.items()} == {
        "API_KEY": {"source": "literal"},
        "BANK_TOKEN": {"source": "secret", "ref": "google_secret_manager_secret.bank_token"},
        "DATABASE_URL": {"source": "reference", "ref": "google_sql_database_instance.main"},  # via var.
        "EVENTS_TOPIC": {"source": "reference", "ref": "google_pubsub_topic.events"},
        "LOG_LEVEL": {"source": "literal"},
    }
    assert api.attrs["image"] == "europe-docker.pkg.dev/acme/apps/recon-api"  # no tag
    assert (api.attrs["min_instances"], api.attrs["max_instances"]) == (1, 4)
    sql = res["google_sql_database_instance.main"]
    assert sql.kind == "managed_datastore" and sql.attrs["encrypted"] is True
    assert "root_password" not in json.dumps(sql.attrs)
    assert res['google_storage_bucket.exports["pdf"]'].action == "delete+create"
    assert res["google_secret_manager_secret_version.bank_token"].kind == "infra_other"
    assert res["google_cloud_scheduler_job.nightly"].refs == {
        "module.services.google_cloud_run_v2_service.this"
    }


def test_aws_plan_maps_ecs_lambda_and_website():
    res = _by_addr(_read(INFRA / "aws" / "plan.json"))
    ecs = res["aws_ecs_service.worker"]
    assert ecs.kind == "deployment_unit" and ecs.env_from == "aws_ecs_task_definition.worker"
    assert ecs.env_vars["API_KEY"].to_dict() == {"source": "secret", "ref": "aws_secretsmanager_secret.api"}
    assert ecs.env_vars["MODE"].source == "literal" and ecs.attrs["image"].endswith("/ingest-worker")
    lam = res["aws_lambda_function.ingest"]
    # one expression for the whole map: keys known only after apply come from a referenced resource
    assert lam.env_vars["QUEUE_URL"].to_dict() == {
        "source": "unknown",
        "candidates": ["aws_dynamodb_table.runs", "aws_sqs_queue.jobs"],
    }
    assert res["aws_s3_bucket.site[0]"].attrs["website"] is True
    assert res["module.alerts[0].aws_sns_topic.this"].kind == "managed_queue"
    assert res["aws_db_instance.main"].attrs["encrypted"] is True


def test_real_opentofu_plan_and_its_static_twin_agree():
    """A plan produced offline by OpenTofu 1.13.1 (fixtures/infra/tofu-real): module instances,
    references through module variables; the static read of the same .tf finds the same references."""
    pr = _read(INFRA / "tofu-real" / "plan.json", "default")
    assert pr.format_version == "1.2"
    unit = _by_addr(pr)['module.svc["api"].terraform_data.unit']
    assert unit.refs == {"random_password.db", "terraform_data.db"}
    sr = static.read_root(
        INFRA / "tofu-real", "cfg", "default", lambda rel: ids.read_normalized(INFRA / "tofu-real" / rel)
    )
    st = {r.base: r for r in sr.resources}
    assert st["module.svc.terraform_data.unit"].refs == unit.refs
    assert st["null_resource.lit"].attrs["multiplicity"] == "unresolved"
    assert sr.modules["module.svc"]["followed"] is True


def test_plan_hash_ignores_key_order_whitespace_bom_and_timestamp(tmp_path):
    raw = (INFRA / "gcp" / "plan.json").read_bytes()
    doc = json.loads(raw)

    def shuffle(x, rng):
        if isinstance(x, dict):
            items = list(x.items())
            rng.shuffle(items)
            return {k: shuffle(v, rng) for k, v in items}
        if isinstance(x, list):
            return [shuffle(v, rng) for v in x]
        return x

    other = shuffle(doc, random.Random(987654))
    other["timestamp"] = "2030-01-01T00:00:00Z"
    text = json.dumps(other, indent=4).replace("\n", "\r\n")
    raw2 = b"\xef\xbb\xbf" + text.encode("utf-8")
    assert plan.content_hash(plan.load_json(raw)) == plan.content_hash(plan.load_json(raw2))
    a, b = _read(INFRA / "gcp" / "plan.json"), plan.read(plan.load_json(raw2), "prod")
    assert [(r.address, r.attrs, {k: v.to_dict() for k, v in r.env_vars.items()}) for r in a.resources] == [
        (r.address, r.attrs, {k: v.to_dict() for k, v in r.env_vars.items()}) for r in b.resources
    ]


def test_unsupported_and_hostile_plans(tmp_path):
    with pytest.raises(InfraInputError, match="format_version"):
        plan.read({"format_version": "2.0"}, "x")
    with pytest.raises(InfraInputError):
        plan.load_json(b"[1, 2]")
    with pytest.raises(InfraInputError):
        plan.load_json(b"{" * 100_000)  # deep nesting
    with pytest.raises(InfraInputError):
        plan.load_json(b"\xff\xfe not utf-8")
    got = plan.read(
        {"format_version": "1.0", "planned_values": {"root_module": {"resources": [None, 3, {"x": 1}]}}}, "x"
    )
    assert got.resources == []
    with pytest.raises(InfraInputError):
        parse_plan_args(["prod=a.json", "prod=b.json"])
    assert parse_plan_args(["a.json"], "dev") == [("dev", Path("a.json"))]


# -- static .tf -------------------------------------------------------------------------------------
def test_static_limits(tmp_path):
    write_tree(
        tmp_path,
        {
            "infra/main.tf": (
                'variable "pw" {\n  sensitive = true\n  default = "PLANTED-static-default-77"\n}\n'
                "locals {\n  db = google_sql_database_instance.db.connection_name\n}\n"
                'resource "google_sql_database_instance" "db" {\n  name = "db"\n}\n'
                'resource "google_cloud_run_v2_service" "api" {\n  name = "api"\n  count = 2\n'
                '  template {\n    containers {\n      env {\n        name  = "DB"\n        value = local.db\n'
                "      }\n    }\n  }\n}\n"
                'module "local" {\n  source = "./mod"\n}\n'
                'module "remote" {\n  source = "git::https://example.com/x.git"\n}\n'
                'module "escape" {\n  source = "../../outside"\n}\n'
            ),
            "infra/mod/main.tf": 'module "deeper" {\n  source = "./x"\n}\nresource "google_pubsub_topic" "t" {\n  name = "t"\n}\n',
            "infra/broken.tf": "resource {{{ not hcl",
        },
    )
    sr = static.read_root(tmp_path, "infra", "default", lambda rel: ids.read_normalized(tmp_path / rel))
    res = {r.address: r for r in sr.resources}
    api = res["google_cloud_run_v2_service.api"]
    assert api.attrs["multiplicity"] == "unresolved"
    assert api.env_vars["DB"].to_dict() == {
        "source": "reference",
        "ref": "google_sql_database_instance.db",
    }  # local
    assert "module.local.google_pubsub_topic.t" in res
    assert sr.modules["module.remote"]["remote"] is True and sr.modules["module.local"]["followed"] is True
    assert sr.modules["module.escape"]["followed"] is False
    assert any("broken.tf: not parsed" in w for w in sr.warnings)
    assert any("nested local module not followed" in w for w in sr.warnings)
    assert "PLANTED" not in json.dumps([r.__dict__ for r in sr.resources], default=str)


def test_infra_yaml_typing_and_rules_hash():
    rules = model.rules()
    for t, spec in rules["types"].items():
        assert spec["kind"] in rules["kinds"], t
        assert set(spec.get("attrs") or {}) <= set(rules["allowed_attrs"]), t
    assert model.kind_of("google_cloud_run_v2_service") == "deployment_unit"
    assert model.kind_of("aws_sqs_queue") == "managed_queue"
    assert model.kind_of("azurerm_linux_web_app") == "infra_other"
    res = pipeline.build(FIXTURE)
    assert res.rules["infra"]["version"] == 1  # covered by rules_hash


# -- secrets policy ---------------------------------------------------------------------------------
def test_planted_secrets_never_reach_the_file_or_its_dump(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(INFRA / "tofu-real" / "cfg", repo / "infra")
    manifest = repo / "ad2v.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\ninfra_root: [infra]\n", encoding="utf-8")
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(
        repo,
        None,
        out,
        infra_plans=[("prod", INFRA / "gcp" / "plan.json"), ("dev", INFRA / "aws" / "plan.json")],
    )
    planted = set()
    for p in (
        INFRA / "gcp" / "plan.json",
        INFRA / "aws" / "plan.json",
        INFRA / "tofu-real" / "cfg" / "main.tf",
    ):
        planted |= set(__import__("re").findall(r"PLANTED[\w-]+|hunter2", p.read_text(encoding="utf-8")))
    assert len(planted) >= 15
    blob = out.read_bytes()
    text = dump.canonical_dump(out, normative_only=False)
    for secret in sorted(planted):
        assert secret.encode() not in blob, secret
        assert secret not in text, secret
    assert b"PLANTED" not in blob and "PLANTED" not in text
    assert b"deploy:" not in blob  # the credential in the remote module URL
    assert validate(out) == []


# -- the bridge ---------------------------------------------------------------------------------------
def _graph(units: list[dict], containers: dict[str, list[str]], env: str = "prod") -> ir.Graph:
    g = ir.Graph()
    sysn = g.add_node(ir.Node("code", "system", "s", "s"))
    for name, reads in containers.items():
        c = g.add_node(ir.Node("code", "container", name, f"container:{name}", parent_id=sysn.id))
        m = g.add_node(
            ir.Node(
                "code", "module", f"{name}/app.py", f"{name}/app.py", parent_id=c.id, path=f"{name}/app.py"
            )
        )
        if reads:
            m.attrs["env_reads"] = reads
            c.attrs["env_reads"] = reads
    root = g.add_node(
        ir.Node("infra", "infra_module", f"infra ({env})", f"infra:{env}", attrs={"env": env, "root": True})
    )
    for u in units:
        attrs = {"env": env, "address": u["address"], **u.get("attrs", {})}
        attrs["env_vars"] = {k: {"source": "literal"} for k in u.get("env", [])}
        g.add_node(
            ir.Node(
                "infra",
                u.get("kind", "deployment_unit"),
                u["address"],
                f"infra:{env}:{u['address']}",
                parent_id=root.id,
                attrs=attrs,
            )
        )
    return g


class _Cfg:
    def __init__(self, deploys=None):
        self.infra_deploys = deploys or {}


def _statuses(g):
    return {(g.nodes[n].qualified_name, e): s for n, e, s, _ in bridge.statuses(g)}


def test_bridge_priorities_ambiguity_and_many_to_many(monkeypatch):
    monkeypatch.setattr(envreads, "collect", lambda graph, sources: {})  # reads are set on the nodes
    # (b) name: "orders-api" ends with "-api"; (c) env overlap for "billing"; "web" is ambiguous by name
    g = _graph(
        [
            {
                "address": "google_cloud_run_v2_service.orders_api",
                "attrs": {"name": "orders-api"},
                "env": ["DB_URL"],
            },
            {
                "address": "google_cloud_run_v2_service.jobs",
                "attrs": {"name": "nightly"},
                "env": ["BILL_DB", "BILL_TOPIC", "X"],
            },
            {"address": "google_cloud_run_v2_service.web1", "attrs": {"name": "web-eu", "image": "r/web-eu"}},
            {"address": "google_cloud_run_v2_service.web2", "attrs": {"name": "web-us", "image": "r/web-us"}},
        ],
        {"api": ["DB_URL"], "billing": ["BILL_DB", "BILL_TOPIC"], "web": [], "lonely": []},
    )
    dec = bridge.link(g, _Cfg(), {})["prod"]
    st = _statuses(g)
    assert st[("container:api", "prod")] == "deployed"
    assert st[("container:billing", "prod")] == "deployed"
    assert st[("container:web", "prod")] == "ambiguous"
    assert st[("container:lonely", "prod")] == "undeployed"
    methods = {g.nodes[c].name: d["method"] for c, d in dec.items()}
    assert methods == {"api": "name", "billing": "env_overlap", "web": "ambiguous_name", "lonely": None}
    # (a) the manifest wins and settles the ambiguity; one unit may deploy several containers
    g2 = _graph(
        [
            {"address": "google_cloud_run_v2_service.web1", "attrs": {"name": "web-eu"}},
            {"address": "google_cloud_run_v2_service.web2", "attrs": {"name": "web-us"}},
        ],
        {"web": [], "admin": []},
    )
    bridge.link(g2, _Cfg({"google_cloud_run_v2_service.web1": ("web", "admin")}), {})
    st2 = _statuses(g2)
    assert st2[("container:web", "prod")] == "deployed" and st2[("container:admin", "prod")] == "deployed"
    # two units with the same image deploy one container (many-to-many): no ambiguity
    g3 = _graph(
        [
            {"address": "google_cloud_run_v2_service.a", "attrs": {"name": "web", "image": "r/web"}},
            {"address": "google_cloud_run_v2_job.b", "attrs": {"name": "web-job", "image": "r/web"}},
        ],
        {"web": []},
    )
    bridge.link(g3, _Cfg(), {})
    assert len([e for e in g3.edges.values() if e.kind == "deploys"]) == 2


def test_env_reads_and_wired_unwired(tmp_path):
    write_tree(
        tmp_path / "r",
        {
            "billing/pyproject.toml": "[project]\nname='billing'\n",
            "billing/app.py": "import os\nA = os.environ['DB_URL']\nB = os.getenv('CACHE_URL')\n",
            "infra/main.tf": (
                'resource "google_sql_database_instance" "db" {\n  name = "db"\n}\n'
                'resource "google_cloud_run_v2_service" "billing" {\n  name = "billing"\n  template {\n    containers {\n'
                '      env {\n        name  = "DB_URL"\n        value = google_sql_database_instance.db.connection_name\n'
                "      }\n    }\n  }\n}\n"
            ),
            "ad2v.yaml": "containers: [{name: billing, paths: [billing]}]\ninfra_root: [infra]\n",
        },
    )
    res = pipeline.build(tmp_path / "r")
    g = res.graph
    st = {(g.nodes[n].qualified_name, e): (s, rs) for n, e, s, rs in bridge.statuses(g)}
    assert st[("container:billing", "default")][0] == "deployed"
    assert st[("billing/app.py", "default")] == (
        "unwired",
        [
            {
                "env_var": "CACHE_URL",
                "kind": "not_provided",
                "units": [
                    ids.node_id(
                        "infra", "deployment_unit", "infra:default:google_cloud_run_v2_service.billing"
                    )
                ],
            }
        ],
    )
    pe = [e for e in g.edges.values() if e.kind == "provides_env"]
    assert len(pe) == 1 and pe[0].attrs["env_vars"] == ["DB_URL"]
    assert any(e.kind == "wires" and e.attrs["env_vars"] == ["DB_URL"] for e in g.edges.values())
    assert g.nodes[ids.node_id("code", "container", "container:billing")].attrs["env_reads"] == [
        "CACHE_URL",
        "DB_URL",
    ]


def test_no_infra_no_bridge_no_claims():
    res = pipeline.build(FIXTURE)
    g = res.graph
    assert not any(n.side == "infra" for n in g.nodes.values())
    assert not any("env_reads" in n.attrs for n in g.nodes.values())  # the code side is unchanged
    assert bridge.statuses(g) == [] and res.epoch.infra_hash == ""
    view = c4.derive(g, res.pairing.statuses, res.pairing.links)
    assert list(view) == [""]
    kinds = {e["kind"] for e in view[""]["elements"].values()}
    assert {"system", "code_container"} <= kinds
    assert all(e["attrs"].get("infra_status") in (None, "unknown") for e in view[""]["elements"].values())


# -- C4 -------------------------------------------------------------------------------------------------
def _bf_file(tmp_path: Path) -> Path:
    y = tmp_path / "bf.yaml"
    assert main(["init", "--repo", str(BF), "--write", str(y)]) == 0
    y.write_text(y.read_text(encoding="utf-8").replace('": ""', '": "/api/v1"'), encoding="utf-8")
    out = tmp_path / "bf.ad2v"
    plans = INFRA / "brownfield-es"
    assert main([
        "extract", "--repo", str(BF), "--manifest", str(y), "--out", str(out),
        "--infra-plan", f"prod={plans / 'prod.json'}", "--infra-plan", f"dev={plans / 'dev.json'}",
    ]) == 0  # fmt: skip
    return out


def test_c4_elements_relations_and_structurizr_golden(tmp_path, capsys):
    out = _bf_file(tmp_path)
    capsys.readouterr()
    conn = store.open_readonly(out)
    try:
        view = c4.load(conn, store.head_epoch(conn))
    finally:
        conn.close()
    assert sorted(view) == ["dev", "prod"]
    prod = {(e["kind"], e["name"]): e for e in view["prod"]["elements"]}
    assert prod[("deployment_unit", "conciliacion-backend")]["attrs"]["deploys"] == ["backend"]
    assert prod[("deployment_unit", "conciliacion-backend")]["attrs"]["unwired"] == ["EXPORT_BUCKET"]
    assert prod[("static_site", "conciliacion-frontend")]["attrs"]["deploys"] == ["frontend"]
    assert prod[("code_container", "worker")]["attrs"]["infra_status"] == "undeployed"
    assert prod[("bucket", "conciliacion-archivo")]["attrs"]["infra_status"] == "infra_orphan"
    assert {
        ("person", n) for n in ("Jefe de finanzas", "Analista de conciliacion", "Operador de tesoreria")
    } <= set(prod)
    rels = {(r["kind"], tuple(r["attrs"].get("env_vars", []))) for r in view["prod"]["relations"]}
    assert rels == {("wires", ("DATABASE_URL",)), ("wires", ("EVENTS_TOPIC",))}
    dev = {(e["kind"], e["name"]) for e in view["dev"]["elements"]}
    assert ("code_container", "frontend") in dev  # not deployed in dev
    assert main(["c4", str(out), "--env", "prod"]) == 0
    dsl = capsys.readouterr().out
    golden = INFRA / "brownfield-es" / "expected-c4-prod.dsl"
    assert dsl == golden.read_text(encoding="utf-8")
    assert main(["c4", str(out), "--env", "prod", "--format", "json"]) == 0
    a = capsys.readouterr().out
    assert main(["c4", str(out), "--env", "prod", "--format", "json"]) == 0
    assert capsys.readouterr().out == a and json.loads(a)["envs"] == ["dev", "prod"]
    assert main(["c4", str(out), "--env", "qa"]) == 2


def test_c4_layout_keeps_slots_across_epochs(tmp_path):
    """Slot persistence: an element keeps its slot while it stays in its row; removing one leaves a gap."""
    els = [{"element_id": f"c4_{i}", "kind": "deployment_unit"} for i in "abcd"]
    first = {p[0]: p for p in c4.place(els, {})}
    prev = {k: (v[1], v[2]) for k, v in first.items()}
    second = {
        p[0]: p
        for p in c4.place(
            [e for e in els if e["element_id"] != "c4_b"]
            + [{"element_id": "c4_0", "kind": "deployment_unit"}],
            prev,
        )
    }
    for k in ("c4_a", "c4_c", "c4_d"):
        assert second[k][1:] == first[k][1:]  # same row, slot and position
    assert second["c4_0"][2] == first["c4_b"][2]  # the freed slot is reused by the new element


def test_c4_layout_stability_over_two_epochs(tmp_path):
    out = _bf_file(tmp_path)
    # a second epoch: the dev plan changes (the frontend appears), prod stays
    plans = INFRA / "brownfield-es"
    dev2 = json.loads((plans / "dev.json").read_text(encoding="utf-8"))
    prodj = json.loads((plans / "prod.json").read_text(encoding="utf-8"))
    front = next(r for r in prodj["planned_values"]["root_module"]["resources"] if r["name"] == "frontend")
    dev2["planned_values"]["root_module"]["resources"].append(front)
    (tmp_path / "dev2.json").write_text(json.dumps(dev2), encoding="utf-8")
    y = tmp_path / "bf.yaml"
    assert main([
        "extract", "--repo", str(BF), "--manifest", str(y), "--into", str(out),
        "--infra-plan", f"prod={plans / 'prod.json'}", "--infra-plan", f"dev={tmp_path / 'dev2.json'}",
    ]) == 0  # fmt: skip
    conn = store.open_readonly(out)
    try:
        rows = store.epoch_rows(conn)
        assert [r["change_kind"] for r in rows] == ["initial", "infra"]
        lay = {}
        for r in rows:
            lay[r["seq"]] = {
                (x["env"], x["element_id"]): (x["row"], x["slot"], x["x"], x["y"])
                for x in conn.execute("SELECT * FROM c4_layout WHERE epoch_id = ?", (r["epoch_id"],))
            }
    finally:
        conn.close()
    common = set(lay[1]) & set(lay[2])
    kept = sum(lay[1][k] == lay[2][k] for k in common)
    assert common and kept / len(common) >= 0.95, (kept, len(common))


def test_history_reads_infra_statically(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    write_tree(
        repo,
        {
            "api/pyproject.toml": "[project]\nname='api'\n",
            "api/app.py": "import os\nX = os.environ['DB']\n",
            "infra/main.tf": 'resource "google_cloud_run_v2_service" "api" {\n  name = "api"\n}\n',
            "ad2v.yaml": "containers: [{name: api, paths: [api]}]\ninfra_root: [infra]\n",
        },
    )

    def git(*a: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *a],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "one")
    (repo / "infra" / "main.tf").write_text(
        'resource "google_cloud_run_v2_service" "api" {\n  name = "api"\n}\nresource "google_storage_bucket" "b" {\n  name = "b"\n}\n',
        encoding="utf-8",
    )
    git("commit", "-q", "-am", "two")
    out = tmp_path / "h.ad2v"
    assert (
        main(
            [
                "history",
                "--repo",
                str(repo),
                "--commits",
                "HEAD~1^!",
                "--into",
                str(out),
                "--manifest",
                "ad2v.yaml",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "history",
                "--repo",
                str(repo),
                "--commits",
                "HEAD~1..HEAD",
                "--into",
                str(out),
                "--manifest",
                "ad2v.yaml",
            ]
        )
        == 0
    )
    conn = store.open_readonly(out)
    try:
        rows = store.epoch_rows(conn)
        assert [r["change_kind"] for r in rows] == ["initial", "infra"]
        head = store.load_graph(conn, rows[-1]["epoch_id"])
        assert any(n.kind == "bucket" and n.attrs.get("source") == "static" for n in head.nodes.values())
    finally:
        conn.close()


def test_init_proposes_infra_root_commands_and_ambiguity_placeholders(tmp_path, capsys):
    write_tree(
        tmp_path / "r",
        {
            "web/package.json": "{}",
            "web/src/a.ts": "export const a = 1;\n",
            "infra/main.tf": (
                'resource "google_cloud_run_v2_service" "a" {\n  name = "web-eu"\n}\n'
                'resource "google_cloud_run_v2_service" "b" {\n  name = "web-us"\n}\n'
            ),
            "infra/modules/x/main.tf": 'resource "google_pubsub_topic" "t" {\n  name = "t"\n}\n',
        },
    )
    assert main(["init", "--repo", str(tmp_path / "r")]) == 0
    out = capsys.readouterr().out
    assert (
        "terraform init && terraform plan -refresh=false -out tfplan && terraform show -json tfplan > plan.json"
        in out
    )
    assert "ad2v never runs it" in out and "infra_root: [infra]" in out
    assert '"google_cloud_run_v2_service.a": ""  # web?' in out
    y = tmp_path / "p.yaml"
    assert main(["init", "--repo", str(tmp_path / "r"), "--write", str(y)]) == 0
    assert main(["init", "--repo", str(tmp_path / "r"), "--check", str(y)]) == 1
    assert "ambiguous deployment for container web" in capsys.readouterr().out
    cfg = from_data(__import__("yaml").safe_load(y.read_text(encoding="utf-8")), tmp_path / "r")
    assert cfg.infra_roots == ("infra",) and cfg.infra_deploys["google_cloud_run_v2_service.a"] == ()


def test_manifest_rejects_infra_roots_outside_the_repo(tmp_path):
    from ad2v.manifest import ManifestError

    for bad in ("../x", "/abs", "C:/x"):
        with pytest.raises(ManifestError):
            from_data({"infra_root": bad}, tmp_path)
    with pytest.raises(ManifestError):
        from_data({"infra": {"deploys": {"a": 3}}}, tmp_path)


def test_large_synthetic_plan_is_parsed_within_limits(tmp_path):
    """2,000 resources generated with seed 987654 (M8 performance, numbers in the report)."""
    doc = synthetic_plan(2000, 987654)
    p = tmp_path / "big.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    r = plan.read(plan.load_json(p.read_bytes()), "prod")
    assert len(r.resources) == 2000


def synthetic_plan(n: int, seed: int) -> dict:
    rng = random.Random(seed)
    types = [
        "google_cloud_run_v2_service",
        "google_pubsub_topic",
        "google_storage_bucket",
        "google_sql_database_instance",
    ]
    resources, cfg = [], []
    for i in range(n):
        t = types[rng.randrange(len(types))]
        name = f"r{i}"
        vals: dict = {"name": f"res-{i}"}
        ex: dict = {"name": {"constant_value": f"res-{i}"}}
        if t == "google_cloud_run_v2_service":
            tgt = f"google_pubsub_topic.r{rng.randrange(n)}"
            vals["template"] = [
                {
                    "containers": [
                        {
                            "image": f"r/img{i % 50}:1",
                            "env": [{"name": "TOPIC"}, {"name": "LEVEL", "value": "x"}],
                        }
                    ]
                }
            ]
            ex["template"] = [{"containers": [{"env": [
                {"name": {"constant_value": "TOPIC"}, "value": {"references": [tgt + ".name", tgt]}},
                {"name": {"constant_value": "LEVEL"}, "value": {"constant_value": "x"}},
            ]}]}]  # fmt: skip
        resources.append(
            {
                "address": f"{t}.{name}",
                "mode": "managed",
                "type": t,
                "name": name,
                "values": vals,
                "sensitive_values": {},
            }
        )
        cfg.append({"address": f"{t}.{name}", "mode": "managed", "type": t, "name": name, "expressions": ex})
    return {
        "format_version": "1.2",
        "planned_values": {"root_module": {"resources": resources}},
        "configuration": {"root_module": {"resources": cfg}},
    }


def test_size_limits_for_hostile_inputs(tmp_path, monkeypatch):
    """docs/security.md (P10 surface): oversized plans are refused, oversized .tf files skipped."""
    monkeypatch.setattr(plan, "MAX_PLAN_BYTES", 1000)
    with pytest.raises(InfraInputError, match="larger than"):
        plan.load_json(b"{" + b" " * 2000 + b"}")
    monkeypatch.setattr(plan, "MAX_RESOURCES", 5)
    with pytest.raises(InfraInputError, match="more than 5 resources"):
        plan.read(synthetic_plan(10, 987654), "x")
    monkeypatch.setattr(static, "MAX_TF_BYTES", 50)
    write_tree(
        tmp_path, {"infra/big.tf": 'resource "google_pubsub_topic" "t" {\n  name = "' + "x" * 200 + '"\n}\n'}
    )
    sr = static.read_root(tmp_path, "infra", "default", lambda rel: ids.read_normalized(tmp_path / rel))
    assert sr.resources == [] and any("skipped" in w for w in sr.warnings)
