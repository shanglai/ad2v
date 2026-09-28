"""CLI for the LLM layer: `ad2v llm plan|run|eval|show-prose`, `ad2v suggestions list|accept|reject`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids, store
from ad2v.llm import api, evaluate, prose, suggest
from ad2v.llm.config import from_data
from ad2v.llm.context import EpochView


def _out(text: str) -> None:
    from ad2v.cli import _out as out

    out(text)


def _table(rows: list[tuple[Any, ...]], header: tuple[str, ...]) -> str:
    from ad2v.cli import _table as table

    return table([tuple(str(c) for c in r) for r in rows], header)


def load_config(a: argparse.Namespace):  # noqa: ANN201
    data: dict[str, Any] = {}
    if getattr(a, "manifest", None):
        raw = yaml.safe_load(Path(a.manifest).read_text(encoding="utf-8")) or {}
        data = dict(raw.get("llm") or {})
    if getattr(a, "provider", None):
        data["provider"] = a.provider
        if a.provider == "fake":
            data["model"] = data.get("model") if data.get("provider") == "fake" else "fake-1"
    if getattr(a, "model", None):
        data["model"] = a.model
    if getattr(a, "replay_dir", None):
        data["fake_replay_dir"] = a.replay_dir
    return from_data(data)


def _opts(a: argparse.Namespace) -> dict[str, Any]:
    o: dict[str, Any] = {}
    for k in ("scope", "mode", "workflow", "spec_root"):
        v = getattr(a, k, None)
        if v:
            o[k] = v
    return o


def _usd(x: float) -> str:
    return f"${x:.4f}"


def _print_report(r: dict[str, Any], fmt: str) -> None:
    if fmt == "json":
        _out(json.dumps(r, indent=2, sort_keys=True) + "\n")
        return
    rows = []
    for t, s in r["tasks"].items():
        rows.append(
            (
                t,
                s["jobs"],
                s["hits"],
                s["misses"],
                s["calls"],
                s["invalid"],
                s["est_input_tokens"],
                s["est_output_tokens"],
                _usd(s["est_cost_usd"]),
                s["input_tokens"],
                s["output_tokens"],
                _usd(s["cost_usd"]),
            )
        )
    head = (
        "task",
        "jobs",
        "cache hits",
        "misses",
        "calls",
        "invalid",
        "est in tok",
        "est out tok",
        "est USD",
        "in tok",
        "out tok",
        "USD",
    )
    _out(
        f"epoch {r['epoch_id']}  provider {r['provider']}  model {r['model']}"
        f"{'  version ' + r['model_version'] if r['model_version'] else ''}  mode {r['mode']}\n"
    )
    _out(_table(rows, head))
    t = r["totals"]
    priced = "" if r["priced"] else " (llm.pricing not set: USD unknown)"
    _out(
        f"estimate: {t['est_input_tokens']} input + {t['est_output_tokens']} output tokens"
        f" ({r['token_counter']}), {_usd(t['est_cost_usd'])}{priced}\n"
    )
    if r["mode"] == "run":
        _out(
            f"actual: {t['calls']} call(s), {t['input_tokens']} input + {t['output_tokens']} output tokens,"
            f" {_usd(t['cost_usd'])}; run {r['run_id']}{'; ABORTED at the budget' if r['aborted'] else ''}\n"
        )


def cmd_plan(a: argparse.Namespace) -> int:
    cfg = load_config(a)
    r = api.plan(
        Path(a.file),
        cfg,
        api.parse_tasks(a.tasks),
        a.epoch,
        count_tokens=a.count_tokens,
        use_cache=not a.no_llm_cache,
        opts=_opts(a),
    )
    _print_report(r, a.format)
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    if a.max_cost_usd is None or not a.yes:
        _out("ad2v llm run needs both --max-cost-usd X and --yes (run `ad2v llm plan` first)\n")
        return 2
    cfg = load_config(a)
    r = api.run(
        Path(a.file),
        cfg,
        api.parse_tasks(a.tasks),
        a.max_cost_usd,
        a.epoch,
        use_cache=not a.no_llm_cache,
        opts=_opts(a),
    )
    _print_report(r, a.format)
    return 3 if r["aborted"] else 0


def cmd_eval(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        runs = a.runs.split(",") if a.runs else None
        r = evaluate.evaluate(conn, evaluate.load_expected(Path(a.expected)), runs)
    finally:
        conn.close()
    if a.format == "json":
        _out(json.dumps(r, indent=2, sort_keys=True) + "\n")
        return 0
    for run in r["runs"]:
        _out(
            f"run {run['run_id']}: {run['labeled_links_judged']} labeled links, accuracy {run['accuracy']},"
            f" kappa {run['kappa']}, validity {run['validity_rate']}\n"
        )
        rows = [
            (s, x["human"], x["verdict"], x["confidence"], "yes" if x["valid"] else "NO")
            for s, x in run["per_link"].items()
        ]
        _out(_table(rows, ("link", "human", "judge", "confidence", "valid")))
    if r["stability"]:
        s = r["stability"]
        _out(f"stability over {len(s['runs'])} runs: {s['identical']}/{s['links']} identical ({s['rate']})\n")
    return 0


def cmd_show_prose(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        view = EpochView(conn, e, from_data({}))
        rows = conn.execute(
            "SELECT * FROM spec_extractions WHERE epoch_id = ? ORDER BY output_path", (e,)
        ).fetchall()
        if not rows:
            _out("no prose extractions in this epoch (run: ad2v llm run --tasks extract-prose)\n")
        for r in rows:
            _out(f"==> {r['output_path']} ({r['state']})\n")
            _out(prose.rendered(conn, view, r["spec_doc_node_id"], r["result_id"]))
    finally:
        conn.close()
    return 0


def cmd_sug_list(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        rows = conn.execute(
            "SELECT s.suggestion_id, s.state, s.confidence, s.lexical_score, s.candidate_rank,"
            " a.qualified_name, b.qualified_name, s.rationale FROM link_suggestions s"
            " JOIN nodes a ON a.epoch_id = s.epoch_id AND a.id = s.spec_node_id"
            " JOIN nodes b ON b.epoch_id = s.epoch_id AND b.id = s.code_node_id"
            " WHERE s.epoch_id = ? ORDER BY s.confidence DESC, s.suggestion_id",
            (e,),
        ).fetchall()
    finally:
        conn.close()
    rows = [r for r in rows if not a.open or r[1] == "open"]
    if a.format == "json":
        keys = (
            "suggestion_id",
            "state",
            "confidence",
            "lexical_score",
            "candidate_rank",
            "spec",
            "code",
            "rationale",
        )
        _out(ids.canonical_json([dict(zip(keys, r, strict=True)) for r in rows]) + "\n")
        return 0
    _out(
        _table(
            [(r[0][:12], r[1], f"{r[2]:.2f}", f"{r[3]:.2f}", r[4], r[5], r[6]) for r in rows],
            ("id", "state", "conf", "bm25", "rank", "spec", "code"),
        )
    )
    return 0


def _decide(a: argparse.Namespace, key: str) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        row = suggest.get_suggestion(conn, e, a.id)
    finally:
        conn.close()
    if row is None:
        _out(f"no suggestion {a.id!r} in epoch {e}\n")
        return 1
    changed = suggest.append_pair(Path(a.manifest), key, row["spec_q"], row["code_q"])
    verb = "accepted" if key == "links" else "rejected"
    _out(
        f"{verb}: {row['spec_q']} <-> {row['code_q']}; "
        + (f"appended to pairing.{key} in {a.manifest}" if changed else "already recorded")
        + ". Re-extract (ad2v extract --into) to make it take effect.\n"
    )
    return 0


def register(sub: argparse._SubParsersAction, epoch_help: str) -> None:
    llm = sub.add_parser("llm", help="the LLM layer: plan, run, evaluate (informative only)")
    lsub = llm.add_subparsers(dest="llm_cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("file")
        p.add_argument("--manifest", help="ad2v.yaml with the `llm:` section")
        p.add_argument(
            "--provider", choices=("fake", "vertex", "openai_compatible"), help="override llm.provider"
        )
        p.add_argument("--model", help="override llm.model")
        p.add_argument("--replay-dir", help="fake provider: directory of recorded outputs")
        p.add_argument(
            "--tasks", help="comma-separated: judge,suggest,summarize,narrate,extract-prose (default all)"
        )
        p.add_argument("--epoch", default="head", help=epoch_help)
        p.add_argument(
            "--scope", choices=("structural", "all"), help="summaries scope (default llm.summaries.scope)"
        )
        p.add_argument("--mode", choices=("containment", "call_depth"), help="narrations projection mode")
        p.add_argument("--workflow", help="narrate only this workflow (id or name)")
        p.add_argument(
            "--no-llm-cache", action="store_true", help="ignore cached results (a new result per call)"
        )
        p.add_argument("--format", choices=("table", "json"), default="table")

    pl = lsub.add_parser("plan", help="calls needed after cache hits, with token and USD estimates")
    common(pl)
    pl.add_argument("--count-tokens", action="store_true", help="use the live provider's countTokens")
    pl.set_defaults(func=cmd_plan)
    rn = lsub.add_parser("run", help="run tasks (needs --max-cost-usd and --yes)")
    common(rn)
    rn.add_argument("--max-cost-usd", type=float)
    rn.add_argument("--yes", action="store_true", help="confirm that live calls may be made and billed")
    rn.add_argument("--spec-root", help="extract-prose: write proposals under <spec-root>/.ad2v-extracted/")
    rn.set_defaults(func=cmd_run)
    ev = lsub.add_parser("eval", help="judge agreement with human labels, kappa, validity, stability")
    ev.add_argument("file")
    ev.add_argument("--expected", required=True, help="expected-judgments.yaml")
    ev.add_argument("--runs", help="comma-separated run ids (default: every run with judge results)")
    ev.add_argument("--format", choices=("table", "json"), default="table")
    ev.set_defaults(func=cmd_eval)
    sp = lsub.add_parser("show-prose", help="print proposed prose-spec extractions")
    sp.add_argument("file")
    sp.add_argument("--epoch", default="head", help=epoch_help)
    sp.set_defaults(func=cmd_show_prose)

    sg = sub.add_parser("suggestions", help="LLM link suggestions: list, accept, reject")
    ssub = sg.add_subparsers(dest="sug_cmd", required=True)
    ls = ssub.add_parser("list")
    ls.add_argument("file")
    ls.add_argument("--open", action="store_true")
    ls.add_argument("--epoch", default="head", help=epoch_help)
    ls.add_argument("--format", choices=("table", "json"), default="table")
    ls.set_defaults(func=cmd_sug_list)
    for name, key in (("accept", "links"), ("reject", "rejected")):
        d = ssub.add_parser(name, help=f"append the pair to pairing.{key} in ad2v.yaml")
        d.add_argument("file")
        d.add_argument("id", help="suggestion id (or a unique prefix)")
        d.add_argument("--manifest", required=True, help="the ad2v.yaml to edit")
        d.add_argument("--epoch", default="head", help=epoch_help)
        d.set_defaults(func=lambda a, key=key: _decide(a, key))
