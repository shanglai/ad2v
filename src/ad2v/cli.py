"""ad2v command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from ad2v import (
    __version__,
    admin,
    c4,
    diff,
    dump,
    gitsource,
    infra,
    ir,
    layout,
    materialize,
    pipeline,
    plugins,
    store,
    unconfigured,
)
from ad2v.cli_init import register as register_init
from ad2v.cli_llm import register as register_llm
from ad2v.cli_plugins import register as register_plugins
from ad2v.cli_specs import register as register_specs
from ad2v.junit import JUnitError
from ad2v.llm.api import LLMRunError
from ad2v.llm.config import LLMConfigError
from ad2v.llm.providers import ProviderError
from ad2v.llm.suggest import ManifestEditError
from ad2v.manifest import ManifestError
from ad2v.mcp.blind import register as register_eval
from ad2v.rules import RulesError
from ad2v.validate import validate


def _out(text: str) -> None:
    """Write UTF-8 with LF line endings on every platform (dumps must be byte-identical)."""
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _table(rows: list[tuple[str, ...]], header: tuple[str, ...]) -> str:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    line = "  ".join("-" * w for w in widths)
    fmt = lambda r: "  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()  # noqa: E731
    return "\n".join([fmt(header), line, *(fmt(r) for r in rows)]) + "\n"


RISK_HEADER = ("rank", "severity", "risk", "workflows", "kind", "qualified_name")


def _risk_row(kind: str, qname: str, attrs: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(attrs["severity_rank"]),
        f"{attrs['severity']:g}",
        ",".join(attrs.get("risk") or []),
        str(attrs["severity_reach"]),
        kind,
        qname,
    )


def summary(res: pipeline.Result, target: str) -> str:
    g = res.graph
    counts = Counter(n.kind for n in g.nodes.values())
    e = res.epoch
    out = [
        f"ad2v {__version__}: wrote epoch #{e.seq} {e.epoch_id} ({e.change_kind}) to {target}\n",
        f"parse cache: {res.stats['cache_hits']} hits, {res.stats['cache_misses']} misses",
        f" ({_rate(res.stats['cache_hits'], res.stats['cache_misses'])})\n",
    ]
    if res.stats.get("unextracted"):  # P8.1 (ADR-0066)
        langs = ", ".join(f"{k} {v}" for k, v in res.stats["unextracted"].items())
        out.append(f"not extracted (no active extractor reads it): {langs} file(s); shown as not_evaluable\n")
    out.append("\n")
    out.append(_table([(k, str(counts[k])) for k in ir.NODE_KINDS if counts[k]], ("kind", "count")))
    ports = sorted((n for n in g.nodes.values() if n.kind in ir.PORT_KINDS), key=lambda n: n.qualified_name)
    if ports:
        out.append("\nPorts\n")
        out.append(
            _table(
                [(p.kind, p.name, p.attrs.get("trigger", ""), p.attrs.get("handler", "")) for p in ports],
                ("kind", "port", "trigger", "handler"),
            )
        )
    risky = [g.nodes[n] for n in res.ranked_behaviors if g.nodes[n].attrs.get("risk")]
    if risky:
        out.append(f"\nTop {min(10, len(risky))} of {len(risky)} risky behaviors by severity\n")
        out.append(_table([_risk_row(n.kind, n.qualified_name, n.attrs) for n in risky[:10]], RISK_HEADER))
    by_side: dict[str, Counter[str]] = {"spec": Counter(), "code": Counter()}
    for nid, st in res.pairing.statuses.items():
        if g.nodes[nid].side in by_side:  # infra nodes have their own dimension (infra_status)
            by_side[g.nodes[nid].side][st.status] += 1
    out.append(f"\nStatus counts (effective node status; spec coverage: {res.meta.get('spec_coverage')})\n")
    out.append(
        _table(
            [
                (s, str(by_side["spec"][s]), str(by_side["code"][s]))
                for s in ir.STATUS_PRECEDENCE
                if by_side["spec"][s] or by_side["code"][s]
            ],
            ("status", "spec", "code"),
        )
    )
    if res.lineage.rows:
        out.append(f"\nLineage: {len(res.lineage.rows)} row(s)\n")
        out.append(
            _table(
                [
                    (m, f"{s:g}", res.lineage_names.get(o, o), g.nodes[n].qualified_name)
                    for o, n, m, s in res.lineage.rows
                ],
                ("method", "score", "from", "to"),
            )
        )
    if res.tests.cases:
        out.append(
            f"\nTest results: {res.tests.cases} cases, {len(res.tests.results)} matched to test functions,"
            f" {len(res.tests.unmatched)} unmatched\n"
        )
        for u in res.tests.unmatched:
            out.append(f"  unmatched ({u['reason']}): {u['classname']}::{u['name']}\n")
    for w in res.pairing.warnings:
        out.append(f"\nwarning: {w['kind']}: {w}\n")
    if g.unresolved:
        out.append("\nUnresolved spec refs\n")
        out.append(
            _table(
                [(u.ref, g.nodes[u.src].qualified_name) for u in sorted(g.unresolved, key=lambda u: u.ref)],
                ("ref", "from"),
            )
        )
    st = res.stats
    inf = st.get("infra") or {}
    if inf:
        kinds = ", ".join(f"{k} {v}" for k, v in inf["kinds"].items()) or "no resources"
        extra = f"; carried from the parent: {', '.join(inf['carried'])}" if inf.get("carried") else ""
        filled = inf.get("filled_from_static") or {}
        if filled:
            extra += "; filled from .tf: " + ", ".join(f"{k} {v}" for k, v in filled.items())
        out.append(f"\nInfra ({', '.join(inf['envs'])}): {kinds}{extra}\n")
        for w in inf.get("warnings", [])[:10]:
            out.append(f"  infra warning: {w}\n")
    out.append(
        f"\n{st['files_code']} code files ({st['loc_code']} lines), {st['files_spec']} spec files,"
        f" {len(g.nodes)} nodes, {len(g.edges)} edges, {len(res.workflows)} workflows"
        f" in {res.elapsed_s:.2f}s\n"
    )
    return "".join(out)


def _rate(hits: int, misses: int) -> str:
    total = hits + misses
    return f"{100 * hits / total:.0f}% hit rate" if total else "no files"


def cmd_extract(a: argparse.Namespace) -> int:
    target = a.into or a.out
    res = pipeline.extract_to_file(
        Path(a.repo),
        [Path(s) for s in a.spec] if a.spec else None,
        Path(target),
        Path(a.manifest) if a.manifest else None,
        test_results=[Path(t) for t in a.test_results or []],
        into=bool(a.into),
        use_cache=not a.no_cache,
        spec_autodetect=not a.no_spec_autodetect,
        extractors=a.extractor or (),
        strict=a.strict,
        plugin_timeout_s=a.plugin_timeout,
        infra_plans=infra.parse_plan_args(a.infra_plan or [], a.infra_env),
    )
    _out(res.spec_roots.describe() + "\n")
    _out(_plugin_lines(res))
    if res.unchanged:
        _out(f"no changes: inputs identical to head epoch {res.epoch.parent_epoch_id}; nothing written\n")
        return 0
    _out(summary(res, target))
    _out(unconfigured_text(res.unconfigured))
    return 0


def unconfigured_text(warnings: list[dict]) -> str:
    """P10 M1 (ADR-0073): the zero-config warning, one line per condition."""
    if not warnings:
        return ""
    lines = ["", "WARNING: " + unconfigured.banner(warnings)]
    lines += [f"  - {w['message']}" for w in warnings]
    return "\n".join(lines) + "\n"


def _plugin_lines(res: pipeline.Result) -> str:
    """Active plug-ins with version and rules hash; failures of skipped ones (ADR-0064)."""
    out = "".join(f"plug-in: {line}\n" for line in res.plugins)
    for r in res.plugin_runs:
        if not r.ok:
            out += f"plug-in FAILED and was skipped: {r.kind} {r.name} {r.version}: {r.error}\n"
        for w in r.warnings:
            out += f"plug-in {r.name}: warning: {w}\n"
    return out


def cmd_history(a: argparse.Namespace) -> int:
    lines: list[str] = []
    shown: list[bool] = []

    def report(commit: str, res: pipeline.Result) -> None:
        if not shown:
            _out("".join(f"plug-in: {line}\n" for line in res.plugins))
            shown.append(True)
        for r in res.plugin_runs:
            if not r.ok:
                _out(f"{commit[:10]}  plug-in FAILED and was skipped: {r.name} {r.version}: {r.error}\n")
        if res.unchanged:
            line = f"{commit[:10]}  no changes (skipped)  [{res.spec_roots.describe()}]"
        else:
            st = res.stats
            line = (
                f"{commit[:10]}  epoch #{res.epoch.seq} {res.epoch.change_kind:10s}"
                f" {len(res.graph.nodes):6d} nodes"
                f"  cache {st['cache_hits']}/{st['cache_hits'] + st['cache_misses']}"
                f"  lineage {len(res.lineage.rows)}  {res.elapsed_s:.2f}s"
                f"  [{res.spec_roots.describe()}]"
            )
        lines.append(line)
        _out(line + "\n")

    gitsource.run_history(
        Path(a.repo),
        a.commits,
        Path(a.into),
        spec_rel=a.spec,
        test_results_rel=a.test_results,
        spec_autodetect=not a.no_spec_autodetect,
        manifest_rel=a.manifest,
        use_cache=not a.no_cache,
        on_epoch=report,
        extractors=a.extractor or (),
        strict=a.strict,
        plugin_timeout_s=a.plugin_timeout,
    )
    _out(f"{len(lines)} commit(s) processed into {a.into}\n")
    return 0


def cmd_dump(a: argparse.Namespace) -> int:
    text = dump.canonical_dump(Path(a.file), normative_only=a.normative_only, epoch=a.epoch)
    if a.out:
        Path(a.out).write_bytes(text.encode("utf-8"))
    else:
        _out(text)
    return 0


def cmd_inspect(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        if a.node:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM nodes WHERE epoch_id = ? AND (id = ? OR qualified_name = ?) ORDER BY id",
                    (e, a.node, a.node),
                )
            ]
            if not rows:
                _out(f"no node matches {a.node!r}\n")
                return 1
            qn = {
                x["id"]: x["qualified_name"]
                for x in conn.execute("SELECT id, qualified_name FROM nodes WHERE epoch_id = ?", (e,))
            }
            for r in rows:
                nid = r["id"]
                info = {
                    k: (json.loads(v) if k.endswith("_json") and isinstance(v, str) else v)
                    for k, v in r.items()
                }
                glyph = conn.execute(
                    "SELECT * FROM glyphs WHERE epoch_id = ? AND node_id = ?", (e, nid)
                ).fetchone()
                if glyph is not None:
                    info["glyph"] = {
                        "base_shape": glyph["base_shape"],
                        "variant": glyph["variant"],
                        "modifiers": json.loads(glyph["modifiers_json"]),
                        "size_weight": glyph["size_weight"],
                    }
                info["out"] = [
                    f"{x['kind']} -> {qn[x['dst']]} (x{x['weight']})"
                    for x in conn.execute(
                        "SELECT * FROM edges WHERE epoch_id = ? AND src = ? ORDER BY kind, dst", (e, nid)
                    )
                ]
                info["in"] = [
                    f"{x['kind']} <- {qn[x['src']]} (x{x['weight']})"
                    for x in conn.execute(
                        "SELECT * FROM edges WHERE epoch_id = ? AND dst = ? ORDER BY kind, src", (e, nid)
                    )
                ]
                _out(json.dumps(info, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            return 0
        if a.top_risk is not None:
            ranked = []
            for r in conn.execute(
                "SELECT kind, qualified_name, attrs_json FROM nodes WHERE epoch_id = ?", (e,)
            ):
                attrs = json.loads(r["attrs_json"])
                if "severity_rank" in attrs and attrs.get("risk"):
                    ranked.append((attrs["severity_rank"], _risk_row(r["kind"], r["qualified_name"], attrs)))
            ranked.sort(key=lambda x: x[0])
            rows_t = [row for _, row in ranked[: a.top_risk]]
            _out(_table(rows_t, RISK_HEADER) if rows_t else "no risky behaviors\n")
            return 0
        sql = "SELECT id, kind, qualified_name, attrs_json FROM nodes WHERE epoch_id = ?"
        params: list[str] = [e]
        if a.kind:
            sql += " AND kind = ?"
            params.append(a.kind)
        sql += " ORDER BY kind, qualified_name"
        out_rows = []
        for r in conn.execute(sql, params):
            attrs = json.loads(r["attrs_json"])
            if a.risk and a.risk not in attrs.get("risk", []):
                continue
            out_rows.append((r["id"], r["kind"], ",".join(attrs.get("risk", [])), r["qualified_name"]))
        _out(
            _table(out_rows, ("id", "kind", "risk", "qualified_name")) if out_rows else "no matching nodes\n"
        )
        return 0
    finally:
        conn.close()


def _brief(reasons: list[dict[str, Any]]) -> str:
    parts = []
    for x in reasons:
        detail = x.get("other") or x.get("from") or x.get("ref") or x.get("handler") or ""
        parts.append(f"{x['kind']}:{x['status']}" + (f"({detail})" if detail else ""))
    return "; ".join(parts)


def cmd_status(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        nodes = {
            r["id"]: r
            for r in conn.execute("SELECT id, side, kind, qualified_name FROM nodes WHERE epoch_id = ?", (e,))
        }
        # P9 (ADR-0069): non-functional requirements are counted apart
        nfr = {
            r["id"]
            for r in conn.execute(
                "SELECT id FROM nodes WHERE epoch_id = ? AND kind = 'requirement'"
                ' AND attrs_json LIKE \'%"requirement_type":"nonfunctional"%\'',
                (e,),
            )
        }
        if store.is_materialized(conn, e):
            statuses = [
                (r["node_id"], r["status"], json.loads(r["reasons_json"])["reasons"])
                for r in conn.execute("SELECT * FROM node_status WHERE epoch_id = ?", (e,))
            ]
        else:
            d = materialize.derive(conn, e)
            statuses = [(nid, s.status, s.reasons) for nid, s in d.pairing.statuses.items()]
    finally:
        conn.close()
    items = []
    for nid, status, reasons in statuses:
        n = nodes[nid]
        if (a.side and n["side"] != a.side) or (a.status and status != a.status):
            continue
        if not a.status and not a.all and status == "none":
            continue
        items.append(
            {
                "id": nid,
                "side": n["side"],
                "kind": n["kind"],
                "qualified_name": n["qualified_name"],
                "status": status,
                "reasons": reasons,
            }
        )
    items.sort(key=lambda i: (i["side"], i["status"], i["kind"], i["qualified_name"]))
    if a.format == "json":
        _out(json.dumps(items, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        return 0
    table = [(i["status"], i["side"], i["kind"], i["qualified_name"], _brief(i["reasons"])) for i in items]
    header = ("status", "side", "kind", "qualified_name", "reasons")
    _out(_table(table, header) if table else "no matching nodes\n")
    if nfr:
        by: dict[str, int] = {}
        for nid, status, _ in statuses:
            if nid in nfr:
                by[status] = by.get(status, 0) + 1
        _out(
            f"\nnon-functional requirements: {len(nfr)} ("
            + ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
            + "); quality / infrastructure requirements, evaluated against infra in P10\n"
        )
    return 0


def cmd_log(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        rows = admin.log(conn)
    finally:
        conn.close()
    if a.format == "json":
        _out(json.dumps(rows, indent=2, sort_keys=True) + "\n")
        return 0
    table = [
        (
            f"{r['seq']}{'*' if r['head'] else ''}",
            r["epoch_id"],
            r["parent"] or "-",
            (r["commit"] or "-")[:10],
            r["change_kind"],
            "yes" if r["pinned"] else "",
            r["label"] or "",
            "yes" if r["materialized"] else "",
            str(r["nodes"]),
        )
        for r in rows
    ]
    header = ("seq", "epoch", "parent", "commit", "change", "pinned", "label", "materialized", "nodes")
    _out(_table(table, header) + "* = head\n")
    return 0


def cmd_pin(a: argparse.Namespace) -> int:
    conn = store.open_rw(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        with conn:
            admin.pin(conn, e, a.label)
    finally:
        conn.close()
    _out(f"pinned {e}" + (f" as {a.label}" if a.label else "") + "\n")
    return 0


def cmd_unpin(a: argparse.Namespace) -> int:
    conn = store.open_rw(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch)
        with conn:
            admin.unpin(conn, e)
    finally:
        conn.close()
    _out(f"unpinned {e}\n")
    return 0


def cmd_prune(a: argparse.Namespace) -> int:
    before = Path(a.file).stat().st_size
    stats = admin.prune_file(Path(a.file), a.keep_last, a.keep_pinned, a.drop_llm_cache)
    after = Path(a.file).stat().st_size
    _out(
        f"removed {stats['epochs_removed']} epoch(s), {stats['version_rows_removed']} version row(s),"
        f" {stats['cache_rows_removed']} cache row(s), {stats['llm_rows_removed']} LLM cache row(s);"
        f" {before / 1e6:.2f} MB -> {after / 1e6:.2f} MB\n"
    )
    return 0


def cmd_materialize(a: argparse.Namespace) -> int:
    if a.epochs:  # `last:N`: the N newest epochs plus every pinned one (what the viewer shows)
        if not a.epochs.startswith("last:") or not a.epochs[5:].isdigit():
            raise ValueError("--epochs must be last:N")
        n = int(a.epochs[5:])
        conn = store.open_readonly(Path(a.file))
        try:
            rows = store.epoch_rows(conn)
            chosen = [r["epoch_id"] for r in rows[-n:]] if n else []
            chosen += [r["epoch_id"] for r in rows if r["pinned"] and r["epoch_id"] not in chosen]
        finally:
            conn.close()
    else:
        chosen = [a.epoch]
    for ref in chosen:
        e, did = pipeline.materialize_epoch(Path(a.file), ref)
        _out(f"{'materialized' if did else 'already materialized'} {e}\n")
    return 0


def chat_service(a: argparse.Namespace):  # noqa: ANN201
    """`ad2v view --chat`: the chat agent (P7, decision 3): needs `llm:` with pricing."""
    from ad2v.chat.agent import ChatService
    from ad2v.cli_llm import load_config
    from ad2v.llm.config import LLMConfigError
    from ad2v.llm.providers import get_provider

    if not a.manifest:
        raise LLMConfigError(
            "--chat needs --manifest ad2v.yaml with an llm: section (provider, model, pricing)"
        )
    cfg = load_config(a)
    if cfg.input_per_mtok is None or cfg.output_per_mtok is None:
        raise LLMConfigError(
            "--chat needs llm.pricing (input_per_mtok, output_per_mtok) for the budget meter"
        )
    return ChatService(Path(a.file), cfg, get_provider(cfg), budget_usd=a.chat_budget_usd)


def cmd_view(a: argparse.Namespace) -> int:  # pragma: no cover - interactive (serve() is tested)
    from ad2v import view
    from ad2v.llm.config import LLMConfigError

    chat = None
    if a.chat:
        try:
            chat = chat_service(a)
        except (LLMConfigError, OSError) as e:
            print(f"ad2v view: {e}", file=sys.stderr)
            return 2
    view.run(Path(a.file), a.port, not a.no_browser, chat=chat)
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    """MCP server over stdio (default) or Streamable HTTP on 127.0.0.1; stdout is protocol-only."""
    from ad2v.mcp import make_server
    from ad2v.mcp.files import FileSet
    from ad2v.mcp.protocol import log

    try:
        files = FileSet(root=Path(a.root)) if a.root else FileSet(single=Path(a.file))
    except (ValueError, OSError) as e:
        print(f"ad2v mcp: {e}", file=sys.stderr)
        return 2
    server = make_server(files)
    if not a.no_warm:  # build the indexes in the background; the first ad2v_locate is then fast
        import threading

        threading.Thread(target=server.ctx.warm, name="ad2v-mcp-warm", daemon=True).start()  # type: ignore[attr-defined]
    if a.http:
        from ad2v.mcp import http

        httpd, url = http.serve(server, a.port)
        log(f"Streamable HTTP on {url} (127.0.0.1 only); Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
        return 0
    from ad2v.mcp import stdio

    log(f"stdio server ready ({len(files.listing())} file(s))")
    stdio.serve(server)
    return 0


def cmd_layout(a: argparse.Namespace) -> int:
    conn = store.open_rw(Path(a.file))
    try:
        wanted = [store.resolve_epoch(conn, a.epoch)] if a.epoch else None
        with conn:
            done = layout.ensure(conn, wanted, a.algorithm)
    finally:
        conn.close()
    _out(f"laid out {len(done)} epoch(s) with {a.algorithm}\n" if done else "layout up to date\n")
    return 0


def cmd_c4(a: argparse.Namespace) -> int:
    """P10 (ADR-0079): the C4 view as a Structurizr DSL workspace or JSON (deterministic)."""
    conn = store.open_readonly(Path(a.file))
    try:
        e = store.resolve_epoch(conn, a.epoch or "head")
        view = c4.load(conn, e)
        system = store.read_meta(conn).get("system_name", "system")
    finally:
        conn.close()
    env = c4.pick_env(view, a.env)
    v = view.get(env, {"elements": [], "relations": [], "layout": {}})
    if a.format == "json":
        text = json.dumps({"system": system, "env": env, "envs": sorted(view), **v}, indent=2, sort_keys=True)
        text += "\n"
    else:
        text = c4.structurizr(system, env, v)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8", newline="\n")
        _out(f"wrote {a.out} ({a.format}, environment {env or '(none)'})\n")
    else:
        _out(text)
    return 0


def cmd_diff(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        to = store.resolve_epoch(conn, a.to)
        frm = store.resolve_epoch(conn, a.frm) if a.frm else store.get_epoch(conn, to).parent_epoch_id
        if frm is None:
            _out("nothing to diff: the target epoch has no parent (use --from)\n")
            return 1
        d = diff.diff(conn, frm, to)
    finally:
        conn.close()
    if a.format == "json":
        _out(json.dumps(d, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    elif a.format == "md":
        _out(diff.to_markdown(d))
    else:
        _out(diff.to_table(d))
    return 0


def cmd_preview_tokens(a: argparse.Namespace) -> int:
    from ad2v import preview

    out = Path(a.out)
    out.write_bytes(preview.render_html().encode("utf-8"))
    _out(f"wrote {out}\n")
    return 0


def cmd_validate(a: argparse.Namespace) -> int:
    problems = validate(Path(a.file), a.epoch)
    if problems:
        _out("".join(f"FAIL {p}\n" for p in problems))
        return 1
    _out(f"OK {a.file} conforms to ad2v format {ir.FORMAT_VERSION}\n")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ad2v", description="agent development to viz: repo + specs -> .ad2v")
    p.add_argument("--version", action="version", version=f"ad2v {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    epoch_help = "epoch id, 'head', 'parent', a pin label, or a commit (prefix)"

    e = sub.add_parser("extract", help="extract a repository and its specs into a .ad2v file")
    e.add_argument("--repo", required=True)
    e.add_argument(
        "--spec",
        action="append",
        help="spec directory or file (repeatable); default: ad2v.yaml spec_root, else auto-detect",
    )
    e.add_argument(
        "--no-spec-autodetect",
        action="store_true",
        help="do not look for specs/, spec/, docs/specs/, .kiro/specs/, sdd/, docs/sdd/",
    )
    e.add_argument("--manifest")
    target = e.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="write a fresh single-epoch file (replaces it)")
    target.add_argument("--into", help="append a new head epoch to this file (created if missing)")
    e.add_argument(
        "--test-results", action="append", metavar="JUNIT_XML", help="JUnit XML results (repeatable)"
    )
    e.add_argument("--no-cache", action="store_true", help="ignore the file's parse cache")
    e.add_argument(
        "--infra-plan",
        action="append",
        metavar="[ENV=]PLAN_JSON",
        help="a Terraform/OpenTofu plan as JSON (`terraform show -json tfplan`), repeatable, one per"
        " environment (prod=plan-prod.json). ad2v only reads the file; it never runs terraform",
    )
    e.add_argument(
        "--infra-env", help="environment name for a --infra-plan given without ENV= (default: default)"
    )
    _plugin_args(e)
    e.set_defaults(func=cmd_extract)

    h = sub.add_parser("history", help="extract a git commit range, one epoch per commit")
    h.add_argument("--repo", required=True)
    h.add_argument("--spec", action="append", help="spec path relative to the repo root (repeatable)")
    h.add_argument(
        "--no-spec-autodetect", action="store_true", help="do not auto-detect spec folders per commit"
    )
    h.add_argument("--manifest", help="manifest path relative to the repo root")
    h.add_argument("--commits", required=True, help="git rev-list range, e.g. HEAD~20..HEAD")
    h.add_argument("--into", required=True)
    h.add_argument(
        "--test-results",
        action="append",
        metavar="REL_PATH",
        help="JUnit XML path relative to the repo root, used when present in a commit",
    )
    h.add_argument("--no-cache", action="store_true")
    _plugin_args(h)
    h.set_defaults(func=cmd_history)

    d = sub.add_parser("dump", help="write the canonical JSONL dump")
    d.add_argument("file")
    d.add_argument("--canonical", action="store_true", help="canonical form (default)")
    d.add_argument("--normative-only", action="store_true", help="drop informative rows and columns")
    d.add_argument("--epoch", default="head", help=f"{epoch_help}, or 'all'")
    d.add_argument("--out")
    d.set_defaults(func=cmd_dump)

    i = sub.add_parser("inspect", help="query nodes")
    i.add_argument("file")
    i.add_argument("--epoch", default="head", help=epoch_help)
    i.add_argument("--node", help="node id or qualified name")
    i.add_argument("--kind", choices=ir.NODE_KINDS)
    i.add_argument("--risk", choices=ir.RISK_FLAGS)
    i.add_argument(
        "--top-risk", type=int, metavar="N", help="the N risky behaviors with the highest severity"
    )
    i.set_defaults(func=cmd_inspect)

    s = sub.add_parser("status", help="list effective spec/code statuses with reasons")
    s.add_argument("file")
    s.add_argument("--epoch", default="head", help=epoch_help)
    s.add_argument("--side", choices=ir.SIDES)
    s.add_argument("--status", choices=ir.NODE_STATUSES)
    s.add_argument("--all", action="store_true", help="include nodes with status 'none'")
    s.add_argument("--format", choices=("table", "json"), default="table")
    s.set_defaults(func=cmd_status)

    df = sub.add_parser("diff", help="what changed between two epochs (default: parent -> head)")
    df.add_argument("file")
    df.add_argument("--from", dest="frm", help=epoch_help)
    df.add_argument("--to", default="head", help=epoch_help)
    df.add_argument("--format", choices=("table", "json", "md"), default="table")
    df.set_defaults(func=cmd_diff)

    lg = sub.add_parser("log", help="list epochs")
    lg.add_argument("file")
    lg.add_argument("--format", choices=("table", "json"), default="table")
    lg.set_defaults(func=cmd_log)

    pn = sub.add_parser("pin", help="pin an epoch (kept by prune, stays materialized)")
    pn.add_argument("file")
    pn.add_argument("epoch", help=epoch_help)
    pn.add_argument("--label")
    pn.set_defaults(func=cmd_pin)

    up = sub.add_parser("unpin", help="unpin an epoch")
    up.add_argument("file")
    up.add_argument("epoch", help=epoch_help)
    up.set_defaults(func=cmd_unpin)

    pr = sub.add_parser("prune", help="drop old epochs and garbage-collect (never the head)")
    pr.add_argument("file")
    pr.add_argument("--keep-last", type=int, required=True)
    pr.add_argument("--keep-pinned", action="store_true")
    pr.add_argument(
        "--drop-llm-cache", action="store_true", help="also delete cached LLM results no epoch references"
    )
    pr.set_defaults(func=cmd_prune)

    mt = sub.add_parser("materialize", help="write derived tables for an epoch (or last:N + pinned)")
    mt.add_argument("file")
    which = mt.add_mutually_exclusive_group(required=True)
    which.add_argument("--epoch", help=epoch_help)
    which.add_argument(
        "--epochs", help="last:N — the N newest epochs plus pinned ones (the viewer shows these)"
    )
    mt.set_defaults(func=cmd_materialize)

    vw = sub.add_parser("view", help="open the viewer for a file (serves on 127.0.0.1 only)")
    vw.add_argument("file")
    vw.add_argument("--port", type=int, default=0, help="0 = any free port")
    vw.add_argument("--no-browser", action="store_true")
    vw.add_argument(
        "--chat",
        action="store_true",
        help="enable the chat panel (your model; needs --manifest with llm: + pricing)",
    )
    vw.add_argument("--manifest", help="ad2v.yaml with the llm: section (for --chat)")
    vw.add_argument(
        "--chat-budget-usd", type=float, default=0.25, help="USD cap for this session (default 0.25)"
    )
    vw.add_argument(
        "--provider", choices=("fake", "vertex", "openai_compatible"), help="override llm.provider"
    )
    vw.add_argument("--model", help="override llm.model")
    vw.add_argument("--replay-dir", help="fake provider: directory of recorded outputs")
    vw.set_defaults(func=cmd_view)

    mc = sub.add_parser("mcp", help="MCP server (read-only tools + the map as an MCP App); stdio by default")
    src_ = mc.add_mutually_exclusive_group(required=True)
    src_.add_argument("--file", help="serve this one .ad2v file")
    src_.add_argument("--root", help="serve every *.ad2v file under this directory")
    mc.add_argument("--http", action="store_true", help="Streamable HTTP on 127.0.0.1 instead of stdio")
    mc.add_argument("--port", type=int, default=0, help="HTTP port (0 = any free port)")
    mc.add_argument("--no-warm", action="store_true", help="do not build search indexes at startup")
    mc.set_defaults(func=cmd_mcp)

    c4p = sub.add_parser("c4", help="the C4 view (context + containers) as Structurizr DSL or JSON")
    c4p.add_argument("file")
    c4p.add_argument("--epoch", help=f"{epoch_help} (default: head)")
    c4p.add_argument("--env", help="infra environment (default: default, else the first)")
    c4p.add_argument("--format", choices=("structurizr", "json"), default="structurizr")
    c4p.add_argument("--out", help="write to this file instead of stdout")
    c4p.set_defaults(func=cmd_c4)

    ly = sub.add_parser("layout", help="deterministic layout (nestgrid-v1) of epochs that lack one")
    ly.add_argument("file")
    ly.add_argument("--epoch", help=f"{epoch_help} (default: every epoch)")
    ly.add_argument(
        "--algorithm",
        choices=layout.ALGORITHMS,
        default=layout.ALGORITHM,
        help="nestgrid-v1 (default) or the experimental shelf packing nestgrid-v2 (ADR-0062)",
    )
    ly.set_defaults(func=cmd_layout)

    t = sub.add_parser("preview-tokens", help="write a static HTML preview of glyphs x statuses x themes")
    t.add_argument("--out", required=True)
    t.set_defaults(func=cmd_preview_tokens)

    v = sub.add_parser("validate", help="check conformance to the format spec")
    v.add_argument("file")
    v.add_argument("--epoch", help=f"{epoch_help} (default: every epoch)")
    v.set_defaults(func=cmd_validate)
    register_llm(sub, epoch_help)
    register_specs(sub)
    register_plugins(sub)
    register_eval(sub)
    register_init(sub)
    return p


def _plugin_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--extractor",
        action="append",
        metavar="NAME",
        help="enable an installed third-party extractor or framework pack for this run (repeatable;"
        " see `ad2v extractors list`). Plug-ins are trusted code that runs in-process",
    )
    sp.add_argument(
        "--strict", action="store_true", help="a failing plug-in aborts the run (default: report and skip it)"
    )
    sp.add_argument(
        "--plugin-timeout",
        type=float,
        default=plugins.DEFAULT_TIMEOUT_S,
        metavar="SECONDS",
        help=f"per third-party plug-in time limit (default {plugins.DEFAULT_TIMEOUT_S:g})",
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (
        store.NotAnAd2vFile,
        ManifestError,
        JUnitError,
        RulesError,
        gitsource.GitError,
        LLMRunError,
        LLMConfigError,
        ProviderError,
        ManifestEditError,
        plugins.PluginError,
        KeyError,
        ValueError,
    ) as e:
        sys.stderr.write(f"ad2v: error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
