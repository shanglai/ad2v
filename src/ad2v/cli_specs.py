"""`ad2v specs bootstrap | review | approve` (P6.1, ADR-0049). Approval is a human act on the CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ad2v import bootstrap
from ad2v.cli_llm import load_config


def _out(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _repo_and_root(a: argparse.Namespace) -> tuple[Path, Path]:
    repo = Path(a.repo).resolve()
    manifest = Path(a.manifest) if getattr(a, "manifest", None) else None
    return repo, bootstrap.spec_root_of(repo, a.spec_root, manifest)


def cmd_bootstrap(a: argparse.Namespace) -> int:
    repo, root = _repo_and_root(a)
    if not a.plan and not a.yes:
        _out("refusing to call a model without --yes (use --plan for the offline estimate)\n")
        return 2
    from ad2v.manifest import load as load_manifest

    rules = load_manifest(repo, Path(a.manifest) if a.manifest else None).spec_markdown
    cfg = load_config(a)
    r = bootstrap.bootstrap(
        repo,
        [Path(p) for p in a.sources],
        cfg,
        spec_root=root,
        cache=Path(a.cache) if a.cache else None,
        plan_only=a.plan,
        max_cost_usd=a.max_cost_usd,
        rules=rules,
    )
    if a.format == "json":
        _out(json.dumps(r, indent=1) + "\n")
        return 0
    _out(f"spec root: {r['spec_root']}\n")
    for f in r["files"]:
        _out(f"  {'yes' if f['qualifies'] else 'no ':3}  {f['path']}  ({f['reason']})\n")
    if "note" in r:
        _out(r["note"] + "\n")
        return 1
    if "plan" in r:
        p = r["plan"]
        cost = f"~${p['est_cost_usd']:.4f}" if r.get("priced") else "unpriced (set llm.pricing)"
        _out(
            f"plan (no calls made): {p['misses']} call(s) ({p['hits']} cached), ~{p['est_input_tokens']} "
            f"input /"
            f" ~{p['est_output_tokens']} output tokens, {cost}\n"
            "run it with --yes --max-cost-usd <cap>\n"
        )
        return 0
    run = r["run"]
    aborted = " (aborted at the budget)" if run["aborted"] else ""
    _out(f"run: {run['calls']} call(s), ${run['spent_usd']:.4f}{aborted}\n")
    for p in r.get("proposals", []):
        _out(f"  proposed {p['proposal']}  <- {p['source']}\n")
    _out("review with `ad2v specs review`, then approve with `ad2v specs approve <proposal>`\n")
    return 0


def cmd_review(a: argparse.Namespace) -> int:
    repo, root = _repo_and_root(a)
    rows = bootstrap.review(repo, root)
    if a.format == "json":
        _out(json.dumps(rows, indent=1) + "\n")
        return 0
    if not rows:
        _out("no proposals\n")
        return 0
    for r in rows:
        state = {True: "STALE (source changed)", False: "current", None: "unknown source"}[r["stale"]]
        _out(
            f"{r['proposal']}  <- {r['source'] or '?'} [{r['source_hash'] or '-'}]  {state}\n"
            f"  model {r['model'] or '?'}; {r['components']} component(s), {r['requirements']} "
            f"requirement(s)\n"
        )
        for o in r["overlaps"]:
            _out(f"  overlap {o['overlap']:.2f}: {o['proposed']} ~ {o['existing']}\n")
        if r["id_clashes"]:
            _out(f"  id clash with the spec tree: {', '.join(r['id_clashes'])}\n")
    return 0


def cmd_approve(a: argparse.Namespace) -> int:
    repo, root = _repo_and_root(a)
    try:
        dest = bootstrap.approve(repo, root, a.proposal, Path(a.to) if a.to else None, a.force_stale)
    except bootstrap.BootstrapError as e:
        _out(f"not approved: {e}\n")
        return 1
    _out(f"approved: moved to {bootstrap._rel(repo, dest)}. Re-extract to parse it.\n")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    sp = sub.add_parser(
        "specs", help="bootstrap specs from prose with an LLM, review and approve the proposals"
    )
    ssub = sp.add_subparsers(dest="specs_cmd", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", default=".", help="repository root (default: .)")
        p.add_argument(
            "--spec-root", help="where proposals go (default: the resolved spec root, else specs/)"
        )
        p.add_argument("--format", choices=("table", "json"), default="table")

    b = ssub.add_parser("bootstrap", help="propose requirements from free-prose files (plan first)")
    common(b)
    b.add_argument(
        "--from", dest="sources", nargs="+", required=True, metavar="PATH", help="files or folders"
    )
    b.add_argument(
        "--plan", action="store_true", help="list qualifying files and the offline estimate; no calls"
    )
    b.add_argument("--yes", action="store_true", help="confirm that model calls may be made and billed")
    b.add_argument("--max-cost-usd", type=float)
    b.add_argument(
        "--cache", help="workspace .ad2v holding the LLM cache (default: <repo>/.ad2v/bootstrap.ad2v)"
    )
    b.add_argument("--manifest", help="ad2v.yaml with the `llm:` section")
    b.add_argument(
        "--provider", choices=("fake", "vertex", "openai_compatible"), help="override llm.provider"
    )
    b.add_argument("--model", help="override llm.model")
    b.add_argument("--replay-dir", help="fake provider: directory of recorded outputs")
    b.set_defaults(func=cmd_bootstrap)

    r = ssub.add_parser("review", help="list proposals: source, model, counts, overlap, staleness")
    common(r)
    r.add_argument("--manifest")
    r.set_defaults(func=cmd_review)

    ap = ssub.add_parser("approve", help="move a proposal into the spec tree (the approval)")
    common(ap)
    ap.add_argument("proposal", help="proposal file name (in <spec-root>/.ad2v-extracted/)")
    ap.add_argument("--to", help="destination folder (default: the spec root)")
    ap.add_argument("--force-stale", action="store_true", help="approve although the source changed")
    ap.add_argument("--manifest")
    ap.set_defaults(func=cmd_approve)
