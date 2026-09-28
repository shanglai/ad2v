"""ad2v command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from ad2v import __version__, admin, diff, dump, gitsource, ir, materialize, pipeline, store
from ad2v.junit import JUnitError
from ad2v.manifest import ManifestError
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
        f" ({_rate(res.stats['cache_hits'], res.stats['cache_misses'])})\n\n",
    ]
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
        Path(a.spec) if a.spec else None,
        Path(target),
        Path(a.manifest) if a.manifest else None,
        test_results=[Path(t) for t in a.test_results or []],
        into=bool(a.into),
        use_cache=not a.no_cache,
    )
    if res.unchanged:
        _out(f"no changes: inputs identical to head epoch {res.epoch.parent_epoch_id}; nothing written\n")
        return 0
    _out(summary(res, target))
    return 0


def cmd_history(a: argparse.Namespace) -> int:
    lines: list[str] = []

    def report(commit: str, res: pipeline.Result) -> None:
        if res.unchanged:
            line = f"{commit[:10]}  no changes (skipped)"
        else:
            st = res.stats
            line = (
                f"{commit[:10]}  epoch #{res.epoch.seq} {res.epoch.change_kind:10s}"
                f" {len(res.graph.nodes):6d} nodes"
                f"  cache {st['cache_hits']}/{st['cache_hits'] + st['cache_misses']}"
                f"  lineage {len(res.lineage.rows)}  {res.elapsed_s:.2f}s"
            )
        lines.append(line)
        _out(line + "\n")

    gitsource.run_history(
        Path(a.repo),
        a.commits,
        Path(a.into),
        spec_rel=a.spec,
        test_results_rel=a.test_results,
        manifest_rel=a.manifest,
        use_cache=not a.no_cache,
        on_epoch=report,
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
    stats = admin.prune_file(Path(a.file), a.keep_last, a.keep_pinned)
    after = Path(a.file).stat().st_size
    _out(
        f"removed {stats['epochs_removed']} epoch(s), {stats['version_rows_removed']} version row(s),"
        f" {stats['cache_rows_removed']} cache row(s); {before / 1e6:.2f} MB -> {after / 1e6:.2f} MB\n"
    )
    return 0


def cmd_materialize(a: argparse.Namespace) -> int:
    e, did = pipeline.materialize_epoch(Path(a.file), a.epoch)
    _out(f"{'materialized' if did else 'already materialized'} {e}\n")
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
    e.add_argument("--spec")
    e.add_argument("--manifest")
    target = e.add_mutually_exclusive_group(required=True)
    target.add_argument("--out", help="write a fresh single-epoch file (replaces it)")
    target.add_argument("--into", help="append a new head epoch to this file (created if missing)")
    e.add_argument(
        "--test-results", action="append", metavar="JUNIT_XML", help="JUnit XML results (repeatable)"
    )
    e.add_argument("--no-cache", action="store_true", help="ignore the file's parse cache")
    e.set_defaults(func=cmd_extract)

    h = sub.add_parser("history", help="extract a git commit range, one epoch per commit")
    h.add_argument("--repo", required=True)
    h.add_argument("--spec", help="spec path relative to the repo root")
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
    pr.set_defaults(func=cmd_prune)

    mt = sub.add_parser("materialize", help="write derived tables for an epoch")
    mt.add_argument("file")
    mt.add_argument("--epoch", required=True, help=epoch_help)
    mt.set_defaults(func=cmd_materialize)

    t = sub.add_parser("preview-tokens", help="write a static HTML preview of glyphs x statuses x themes")
    t.add_argument("--out", required=True)
    t.set_defaults(func=cmd_preview_tokens)

    v = sub.add_parser("validate", help="check conformance to the format spec")
    v.add_argument("file")
    v.add_argument("--epoch", help=f"{epoch_help} (default: every epoch)")
    v.set_defaults(func=cmd_validate)
    return p


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
        KeyError,
        ValueError,
    ) as e:
        sys.stderr.write(f"ad2v: error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
