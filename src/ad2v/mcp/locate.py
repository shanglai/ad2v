"""`ad2v_locate`: a question in natural language -> ranked node ids, deterministically (no LLM).

BM25F-lite: one BM25 index per field (P4's stdlib BM25 and tokenizer), a weighted sum over
fields, then multiplied by kind priors that the question's wording selects (ports and containers
for "where", behaviors for "risk", spec items for "requirement", …) and by a status boost when
the question names a status ("drifting", "missing", …).

The weights live in the rules file (`retrieval:`), so they are covered by `rules_hash`; a file
whose stored rules predate them uses the bundled rules (ADR-0043).
"""

from __future__ import annotations

import functools
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from ad2v import rules as rules_mod
from ad2v import store
from ad2v.llm.suggest import BM25, STOPWORDS, stem
from ad2v.mcp import slices
from ad2v.mcp.index import EpochIndex

_stem = functools.lru_cache(maxsize=None)(stem)


def tokens(text: str) -> list[str]:
    """ad2v.llm.suggest.tokens with a memoized stemmer (same output, ~10x faster on big repos)."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


FIELDS = ("name", "qname", "code", "spec", "summary", "narration")
STATUS_WORDS = {
    "drift": "drift",
    "drifting": "drift",
    "drifted": "drift",
    "missing": "missing",
    "unimplemented": "missing",
    "orphan": "orphan",
    "orphaned": "orphan",
    "unlinked": "orphan",
    "stale": "stale",
    "outdated": "stale",
    "verified": "verified",
    "tested": "verified",
    "review": "needs_review",
    # P8.1 (ADR-0066)
    "unevaluated": "not_evaluable",
    "evaluable": "not_evaluable",
    "unsupported": "not_evaluable",
}
STATUS_STEMS = {stem(w): s for w, s in STATUS_WORDS.items()}  # "drifts", "drifting" -> drift

# P7 retrieval v2 (ADR-0054): spec ids in a question, matched exactly against spec items
QUERY_ID = re.compile(
    r"(?<![\w:.-])((?:[a-z0-9][a-z0-9-]*:)?[A-Za-z][A-Za-z0-9]*-X?[0-9]+(?:\.[0-9]+)?)(?![\w.-])",
    re.I,
)
SUB_ID = re.compile(r"(?<![\w.-])([0-9]+\.[0-9]+)(?![\w.])")  # a Kiro criterion: "1.2"
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py|[^/]*_test\.py)")
RESOURCE_WORDS = {
    "datastore": "datastore database db store table",
    "queue": "queue topic subscription events messages",
    "external_service": "external service api client",
    "llm_endpoint": "llm model endpoint ai",
    "ui": "ui frontend page",
}
# P10 (ADR-0078): infra kinds and infra statuses, in words people use
INFRA_WORDS = {
    "deployment_unit": "service deployment unit runs deploys hosts cloud run lambda ecs function",
    "managed_datastore": "managed datastore database db sql instance",
    "managed_queue": "managed queue topic pubsub sqs sns",
    "bucket": "bucket storage files website static site",
    "secret_store": "secret store secrets manager",
    "network": "network vpc",
    "scheduler": "scheduler cron schedule job",
    "infra_other": "infrastructure resource",
    "infra_module": "terraform module infrastructure",
}
INFRA_STATUS_WORDS = {
    "deployed": "deployed runs on",
    "undeployed": "undeployed not deployed no deployment",
    "wired": "wired provided",
    "unwired": "unwired missing env var not provided environment variable",
    "in_use": "in use",
    "infra_orphan": "orphan unused nobody uses",
    "ambiguous": "ambiguous several candidates",
}
TOUCH_EDGES = ("reads", "writes", "publishes", "consumes", "invokes_llm", "invokes_external")


def query_ids(question: str) -> tuple[set[str], set[str]]:
    """Spec ids written in the question (upper-cased, namespace kept) and bare sub-ids ("1.2")."""
    ids = {
        m if ":" not in m else m.split(":", 1)[0].lower() + ":" + m.split(":", 1)[1]
        for m in QUERY_ID.findall(question)
    }
    ids = {i.split(":", 1)[0] + ":" + i.split(":", 1)[1].upper() if ":" in i else i.upper() for i in ids}
    return ids, set(SUB_ID.findall(question))


def id_matches(spec_id: str, ids: set[str], subs: set[str]) -> bool:
    if spec_id in ids:
        return True
    bare = spec_id.split(":", 1)[1] if ":" in spec_id else spec_id
    return bare in ids or any(bare.endswith("-" + s) for s in subs)


def _bundled_retrieval() -> dict[str, Any]:
    return rules_mod.load().get("retrieval") or {}


def retrieval_rules(conn: sqlite3.Connection, epoch_id: str) -> dict[str, Any]:
    """The `retrieval:` section of the rules this epoch was extracted with, else the bundled one."""
    try:
        rh = store.get_epoch(conn, epoch_id).rules_hash
        stored = store.load_rules(conn, rh).get("retrieval")
    except Exception:  # noqa: BLE001 - an old file without stored rules
        stored = None
    # keys the stored section predates (P7: propagation, id_match, tests) come from the bundled rules
    return {**_bundled_retrieval(), **stored} if stored else _bundled_retrieval()


@dataclass
class Locator:
    weights: dict[str, float]
    priors: dict[str, dict[str, Any]]
    status_boost: float
    prefix_min: int = 0
    # P7 retrieval v2 (ADR-0054), from the `retrieval:` rules
    link_lambda: float = 0.0  # spec score = max(own, lambda * best linked code score), and back
    spec_intents: tuple[str, ...] = ()
    spec_side_boost: float = 1.0  # a spec intent prefers spec items
    code_intents: tuple[str, ...] = ()
    id_match: float = 0.0  # added when the question names the item's spec id
    test_factor: float = 1.0  # test code, unless the question is about tests
    test_triggers: frozenset[str] = frozenset()
    linked: dict[str, list[str]] = field(default_factory=dict)
    spec_ids: dict[str, str] = field(default_factory=dict)
    is_test: set[str] = field(default_factory=set)
    sides: dict[str, str] = field(default_factory=dict)
    k1_docs: dict[str, BM25] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    status: dict[str, set[str]] = field(default_factory=dict)
    build_ms: float = 0.0

    def rank(
        self,
        question: str,
        k: int = 10,
        side: str | None = None,
        kind: str | None = None,
        ix: EpochIndex | None = None,
    ) -> list[dict[str, Any]]:
        q = tokens(question)
        words = set(question.lower().replace("?", " ").replace(",", " ").split())
        qset = set(q)
        if self.prefix_min:  # "night" also matches "nightly", "classifi" (classified) matches "classify"
            vocab = self._vocab()
            q = q + sorted(
                {v for t in qset if len(t) >= self.prefix_min for v in vocab if v != t and v.startswith(t)}
            )
        mult: dict[str, float] = {}
        fired: list[str] = []
        for name, p in self.priors.items():
            trig = set(p.get("triggers", []))
            if words & trig or qset & {tokens(t)[0] for t in trig if tokens(t)}:
                fired.append(name)
                for kd, m in (p.get("kinds") or {}).items():
                    mult[kd] = mult.get(kd, 1.0) * float(m)
        wanted_status = sorted({STATUS_STEMS[stem(w)] for w in words if stem(w) in STATUS_STEMS})
        raw: dict[str, tuple[float, dict[str, float]]] = {}
        for nid in self.kinds:
            per: dict[str, float] = {}
            total = 0.0
            for f in FIELDS:
                w = self.weights.get(f, 0.0)
                bm = self.k1_docs.get(f)
                if not w or bm is None or nid not in bm.tf:
                    continue
                s = bm.score(q, nid)
                if s:
                    per[f] = round(s * w, 4)
                    total += s * w
            if total:
                raw[nid] = (total, per)
        # link propagation (P7): with a spec intent a spec item scores at least lambda x its best
        # normatively linked code item, and symmetrically with a code intent
        to_side = set()
        if self.link_lambda and set(fired) & set(self.spec_intents):
            to_side.add("spec")
        if self.link_lambda and set(fired) & set(self.code_intents):
            to_side.add("code")
        if to_side:
            prop: dict[str, tuple[float, dict[str, float]]] = {}
            for nid, partners in self.linked.items():
                if self.sides.get(nid) not in to_side:
                    continue
                best = max((raw[p][0] for p in partners if p in raw), default=0.0) * self.link_lambda
                own = raw.get(nid, (0.0, {}))
                if best > own[0]:
                    prop[nid] = (best, {**own[1], "linked": round(best, 4)})
            raw.update(prop)
        q_ids, q_subs = query_ids(question) if self.id_match else (set(), set())
        about_tests = bool(words & self.test_triggers)
        scored: list[tuple[float, str, dict[str, float]]] = []
        for nid, kd in self.kinds.items():
            if kind and kd != kind:
                continue
            if side and ix is not None and ix.nodes[nid]["side"] != side:
                continue
            total, per = raw.get(nid, (0.0, {}))
            per = dict(per)
            sid = self.spec_ids.get(nid)
            if sid and (q_ids or q_subs) and id_matches(sid, q_ids, q_subs):
                total += self.id_match
                per["id"] = self.id_match
            if total and "spec" in to_side and self.sides.get(nid) == "spec":
                total *= self.spec_side_boost
            if total and nid in self.is_test and not about_tests:
                total *= self.test_factor
            if wanted_status and self.status.get(nid, set()) & set(wanted_status):
                total = (total + 1.0) * self.status_boost
                per["status"] = self.status_boost
            if total <= 0:
                continue
            total *= mult.get(kd, 1.0)
            scored.append((round(total, 6), nid, per))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [
            {"id": nid, "score": s, "matched": sorted(per, key=lambda f: -per[f]), "intents": fired}
            for s, nid, per in scored[:k]
        ]

    def _vocab(self) -> list[str]:
        v = getattr(self, "_vocab_cache", None)
        if v is None:
            v = sorted({t for bm in self.k1_docs.values() for t in bm.idf})
            self._vocab_cache = v
        return v


def build(conn: sqlite3.Connection, ix: EpochIndex) -> Locator:
    t0 = time.perf_counter()
    cfg = retrieval_rules(conn, ix.epoch_id)
    docs: dict[str, dict[str, list[str]]] = {f: {} for f in FIELDS}
    code_lines = _code_heads(conn, ix)
    narr = _narrations_by_node(conn, ix)
    touched = _touched_by(conn, ix)
    infra = slices.infra_status(conn, ix.epoch_id)
    deploys: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT src, dst FROM edges WHERE epoch_id = ? AND kind = 'deploys'", (ix.epoch_id,)
    ):
        if r["dst"] in ix.nodes:
            deploys.setdefault(r["src"], []).append(ix.nodes[r["dst"]]["name"])
    for nid, n in ix.nodes.items():
        a = ix.attrs.get(nid, {})
        docs["name"][nid] = tokens(n["name"] + " " + str(a.get("title", "")))
        docs["qname"][nid] = tokens(n["qname"].replace("/", " ").replace("::", " ").replace(".", " "))
        code = [
            str(a.get(k, ""))
            for k in ("path", "method", "command", "tool_name", "handler", "topic", "schedule")
        ]
        code += [str(t) for t in a.get("risk", [])] + [str(t) for t in a.get("touches", [])]
        code.append(code_lines.get(nid, ""))
        if n["kind"] in RESOURCE_WORDS:  # P7: what it is, and the functions that touch it
            code.append(RESOURCE_WORDS[n["kind"]])
            code += [ix.nodes[f]["name"] for f in touched.get(nid, [])]
        if n["side"] == "infra":  # P10: kind, type, env vars, what it deploys
            code += [INFRA_WORDS.get(n["kind"], ""), str(a.get("type", "")), str(a.get("env", ""))]
            code += list((a.get("env_vars") or {}).keys()) + deploys.get(nid, [])
        for st in (infra.get(nid) or {}).values():
            code.append(INFRA_STATUS_WORDS.get(st, ""))
        code += [str(x) for x in a.get("env_reads", [])]
        docs["code"][nid] = tokens(" ".join(code))
        if n["side"] == "spec":
            spec = [
                str(a.get(k, ""))
                for k in ("text", "response", "trigger", "system", "summary", "method", "path", "title")
            ]
            spec += [str(s) for s in a.get("steps", [])] if isinstance(a.get("steps"), list) else []
            docs["spec"][nid] = tokens(" ".join(spec))
        s = ix.summaries.get(nid)
        if s:
            docs["summary"][nid] = tokens(
                " ".join(x for x in (s.get("label"), s.get("card"), s.get("deep")) if x)
            )
        if nid in narr:
            docs["narration"][nid] = tokens(narr[nid])
    bms = {f: BM25({k: v for k, v in d.items() if v}) for f, d in docs.items() if any(d.values())}
    st: dict[str, set[str]] = {}
    for nid in ix.nodes:
        st[nid] = {ix.norm.get(nid, {}).get("status", "none"), ix.eff.get(nid, {}).get("status", "none")}
    prop = cfg.get("propagation") or {}
    tests = cfg.get("tests") or {}
    linked, spec_ids, is_test = _links(conn, ix), {}, set()
    for nid, n in ix.nodes.items():
        a = ix.attrs.get(nid, {})
        if n["side"] == "spec" and n["kind"] in ("requirement", "spec_component", "scenario"):
            spec_ids[nid] = str(a.get("spec_id") or n["qname"])
        if n["side"] == "code" and (a.get("is_test") or TEST_PATH.search(n["path"] or n["qname"])):
            is_test.add(nid)
    loc = Locator(
        link_lambda=float(prop.get("lambda", 0.0)),
        spec_intents=tuple(prop.get("spec_intents", [])),
        spec_side_boost=float(prop.get("spec_side_boost", 1.0)),
        code_intents=tuple(prop.get("code_intents", [])),
        id_match=float(cfg.get("id_match", 0.0)),
        test_factor=float(tests.get("factor", 1.0)),
        test_triggers=frozenset(tests.get("triggers", [])),
        linked=linked,
        spec_ids=spec_ids,
        is_test=is_test,
        sides={nid: n["side"] for nid, n in ix.nodes.items()},
        weights={k: float(v) for k, v in (cfg.get("field_weights") or {}).items()},
        priors=cfg.get("intents") or {},
        status_boost=float(cfg.get("status_boost", 2.0)),
        prefix_min=int(cfg.get("prefix_min", 0)),
        k1_docs=bms,
        kinds={nid: n["kind"] for nid, n in ix.nodes.items()},
        status=st,
    )
    loc.build_ms = (time.perf_counter() - t0) * 1000
    return loc


def _code_heads(conn: sqlite3.Connection, ix: EpochIndex, max_lines: int = 12) -> dict[str, str]:
    """The def line and docstring (first lines of the span) of code nodes, and of port handlers."""
    by_q: dict[tuple[str, str], str] = {(n["kind"], n["qname"]): i for i, n in ix.nodes.items()}
    files: dict[str, list[str] | None] = {}
    module_hash = {  # one query, not one per module: `nodes` is a view over the version tables
        r["qualified_name"]: r["content_hash"]
        for r in conn.execute(
            "SELECT qualified_name, content_hash FROM nodes WHERE epoch_id = ? AND kind = 'module'",
            (ix.epoch_id,),
        )
    }

    def lines_of(path: str | None) -> list[str] | None:
        if path is None:
            return None
        if path not in files:
            h = module_hash.get(path)
            text = store.load_source(conn, h) if h else None
            files[path] = text.split("\n") if text is not None else None
        return files[path]

    out: dict[str, str] = {}
    for nid, n in ix.nodes.items():
        if (
            n["side"] != "code"
            or n["kind"] not in ("function", "class", "module")
            and not n["kind"].endswith(("_route", "_command", "_tool", "_consumer"))
        ):
            continue
        target = n
        h = ix.attrs.get(nid, {}).get("handler")
        if h:
            for kd in ("function", "module", "class"):
                t = by_q.get((kd, h))
                if t is not None:
                    target = ix.nodes[t]
                    break
        lines = lines_of(target["path"])
        s = target["spanStart"] or 1
        e = min(target["spanEnd"] or s, s + max_lines - 1)
        if lines is None:
            continue
        out[nid] = " ".join(lines[i - 1] for i in range(s, min(e, len(lines)) + 1))
    return out


def _links(conn: sqlite3.Connection, ix: EpochIndex) -> dict[str, list[str]]:
    """Deterministic spec<->code links of a materialized epoch, both directions (P7)."""
    out: dict[str, set[str]] = {}
    try:
        rows = conn.execute(
            "SELECT spec_node_id, code_node_id FROM links WHERE epoch_id = ? AND provenance = 'deterministic'"
            " AND spec_node_id IS NOT NULL AND code_node_id IS NOT NULL",
            (ix.epoch_id,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    for s, c in rows:
        if s in ix.nodes and c in ix.nodes:
            out.setdefault(s, set()).add(c)
            out.setdefault(c, set()).add(s)
    return {k: sorted(v) for k, v in out.items()}


def _touched_by(conn: sqlite3.Connection, ix: EpochIndex) -> dict[str, list[str]]:
    """resource node -> the functions that read, write, publish, consume or invoke it (P7)."""
    out: dict[str, set[str]] = {}
    marks = ",".join("?" * len(TOUCH_EDGES))
    for src, dst in conn.execute(
        f"SELECT src, dst FROM edges WHERE epoch_id = ? AND kind IN ({marks})", (ix.epoch_id, *TOUCH_EDGES)
    ):
        if src in ix.nodes and dst in ix.nodes:
            out.setdefault(dst, set()).add(src)
    return {k: sorted(v) for k, v in out.items()}


def _narrations_by_node(conn: sqlite3.Connection, ix: EpochIndex) -> dict[str, str]:
    """Narration text attached to each workflow's entry node (informative text, BM25 only)."""
    out: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT w.entry_node_id, n.text FROM narrations n JOIN workflows w"
        " ON w.epoch_id = n.epoch_id AND w.workflow_id = n.workflow_id WHERE n.epoch_id = ?"
        " ORDER BY w.entry_node_id, n.detail_level, n.span_start",
        (ix.epoch_id,),
    ).fetchall()
    for r in rows:
        out.setdefault(r["entry_node_id"], []).append(r["text"])
    return {k: " ".join(v) for k, v in out.items()}
