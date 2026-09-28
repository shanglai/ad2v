"""ad2v command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from ad2v import __version__, dump, ir, pipeline, store
from ad2v.manifest import ManifestError
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


def cmd_extract(a: argparse.Namespace) -> int:
    res = pipeline.extract_to_file(
        Path(a.repo), Path(a.spec) if a.spec else None, Path(a.out), Path(a.manifest) if a.manifest else None
    )
    g = res.graph
    counts = Counter(n.kind for n in g.nodes.values())
    out = [f"ad2v {__version__}: wrote {a.out}\n\n"]
    out.append(_table([(k, str(counts[k])) for k in ir.NODE_KINDS if counts[k]], ("kind", "count")))
    ports = sorted((n for n in g.nodes.values() if n.kind in ir.PORT_KINDS), key=lambda n: n.qualified_name)
    if ports:
        out.append("\nPorts\n")
        out.append(
            _table([(p.kind, p.name, p.attrs.get("handler", "")) for p in ports], ("kind", "port", "handler"))
        )
    risky = sorted((n for n in g.nodes.values() if n.attrs.get("risk")), key=lambda n: n.qualified_name)
    if risky:
        out.append("\nRisky behaviors\n")
        out.append(
            _table(
                [(n.kind, ",".join(n.attrs["risk"]), n.qualified_name) for n in risky],
                ("kind", "risk", "where"),
            )
        )
    if res.workflows:
        out.append("\nWorkflows\n")
        out.append(
            _table([(w.side, w.name, str(len(w.steps))) for w in res.workflows], ("side", "name", "steps"))
        )
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
        f" {len(g.nodes)} nodes, {len(g.edges)} edges in {res.elapsed_s:.2f}s\n"
    )
    _out("".join(out))
    return 0


def cmd_dump(a: argparse.Namespace) -> int:
    text = dump.canonical_dump(Path(a.file))
    if a.out:
        Path(a.out).write_bytes(text.encode("utf-8"))
    else:
        _out(text)
    return 0


def _find_node(conn: object, key: str) -> list[dict[str, object]]:
    rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT * FROM nodes WHERE id = ? OR qualified_name = ? ORDER BY id", (key, key)
    ).fetchall()
    return [dict(r) for r in rows]


def cmd_inspect(a: argparse.Namespace) -> int:
    conn = store.open_readonly(Path(a.file))
    try:
        if a.node:
            rows = _find_node(conn, a.node)
            if not rows:
                _out(f"no node matches {a.node!r}\n")
                return 1
            for r in rows:
                nid = r["id"]
                info = {
                    k: (json.loads(v) if k.endswith("_json") and isinstance(v, str) else v)
                    for k, v in r.items()
                }
                glyph = conn.execute("SELECT * FROM glyphs WHERE node_id = ?", (nid,)).fetchone()
                if glyph is not None:
                    info["glyph"] = {
                        "base_shape": glyph["base_shape"],
                        "variant": glyph["variant"],
                        "modifiers": json.loads(glyph["modifiers_json"]),
                        "size_weight": glyph["size_weight"],
                    }
                qn = {
                    x["id"]: x["qualified_name"] for x in conn.execute("SELECT id, qualified_name FROM nodes")
                }
                info["out"] = [
                    f"{e['kind']} -> {qn[e['dst']]} (x{e['weight']})"
                    for e in conn.execute("SELECT * FROM edges WHERE src = ? ORDER BY kind, dst", (nid,))
                ]
                info["in"] = [
                    f"{e['kind']} <- {qn[e['src']]} (x{e['weight']})"
                    for e in conn.execute("SELECT * FROM edges WHERE dst = ? ORDER BY kind, src", (nid,))
                ]
                _out(json.dumps(info, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            return 0
        sql = "SELECT id, kind, qualified_name, attrs_json FROM nodes WHERE 1=1"
        params: list[str] = []
        if a.kind:
            sql += " AND kind = ?"
            params.append(a.kind)
        sql += " ORDER BY kind, qualified_name"
        rows = []
        for r in conn.execute(sql, params):
            attrs = json.loads(r["attrs_json"])
            if a.risk and a.risk not in attrs.get("risk", []):
                continue
            rows.append((r["id"], r["kind"], ",".join(attrs.get("risk", [])), r["qualified_name"]))
        _out(_table(rows, ("id", "kind", "risk", "qualified_name")) if rows else "no matching nodes\n")
        return 0
    finally:
        conn.close()


def cmd_validate(a: argparse.Namespace) -> int:
    problems = validate(Path(a.file))
    if problems:
        _out("".join(f"FAIL {p}\n" for p in problems))
        return 1
    _out(f"OK {a.file} conforms to ad2v format {ir.FORMAT_VERSION}\n")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ad2v", description="agent development to viz: repo + specs -> .ad2v")
    p.add_argument("--version", action="version", version=f"ad2v {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="extract a repository and its specs into a .ad2v file")
    e.add_argument("--repo", required=True)
    e.add_argument("--spec")
    e.add_argument("--manifest")
    e.add_argument("--out", required=True)
    e.set_defaults(func=cmd_extract)

    d = sub.add_parser("dump", help="write the canonical JSONL dump")
    d.add_argument("file")
    d.add_argument("--canonical", action="store_true", help="canonical form (the only form in v0.1)")
    d.add_argument("--out")
    d.set_defaults(func=cmd_dump)

    i = sub.add_parser("inspect", help="query nodes")
    i.add_argument("file")
    i.add_argument("--node", help="node id or qualified name")
    i.add_argument("--kind", choices=ir.NODE_KINDS)
    i.add_argument("--risk", choices=ir.RISK_FLAGS)
    i.set_defaults(func=cmd_inspect)

    v = sub.add_parser("validate", help="check conformance to the format spec")
    v.add_argument("file")
    v.set_defaults(func=cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (store.NotAnAd2vFile, ManifestError) as e:
        sys.stderr.write(f"ad2v: error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
