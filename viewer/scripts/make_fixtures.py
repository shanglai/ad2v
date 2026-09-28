"""Generate the viewer's test fixtures and the demo data (run by `npm run fixtures`).

Outputs (all gitignored, regenerated from the repository):
- tests/fixtures/demo.ad2v: the payments-recon P3 history scenario (8 epochs, all materialized and
  laid out) with informative LLM rows at the head from a replay-only *fake* provider (labeled
  "fake" in the UI; no LLM is called);
- tests/fixtures/projections.json: Python's project(containment) of every code workflow at every
  depth, and narrate.levels(), for the TypeScript parity test;
- tests/fixtures/styles.json: the normative status styles and overlay badges (tokens.py);
- src/generated/demo-data.ts: the demo file as base64, embedded by `vite build --mode demo`.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
VIEWER = HERE.parent
REPO = VIEWER.parent
sys.path.insert(0, str(REPO / "tests"))

from history_scenario import Scenario  # noqa: E402

from ad2v import gitsource, ir, layout, materialize, store, tokens, workflows  # noqa: E402
from ad2v.llm import api, judge, narrate  # noqa: E402
from ad2v.llm.config import from_data  # noqa: E402
from ad2v.llm.context import EpochView  # noqa: E402
from ad2v.llm.providers import ProviderError  # noqa: E402
from ad2v.llm.providers.fake import FakeProvider  # noqa: E402


class ReplayOnly(FakeProvider):
    """The fake provider without its synthetic fallback: unknown subjects get no result."""

    def generate(self, task, system, user_parts, response_schema, params):  # noqa: ANN001, ANN201
        if (task, str(params.get("subject"))) not in self.recordings:
            raise ProviderError("no demo recording for this subject")
        return super().generate(task, system, user_parts, response_schema, params)


SUMMARIES = {  # hand-written demo cards (fake provider), keyed by qualified name
    "payments-recon": (
        "Payments reconciliation: an API and a nightly worker that match bank statements against the ledger.",
        "Two containers. The api container serves HTTP routes and an MCP tool to start reconciliation runs, "
        "read their status and list unmatched transactions; it matches transactions against the ledger "
        "database and labels unmatched rows with an LLM. The worker container runs the nightly batch and "
        "publishes run-completed events on Pub/Sub.",
    ),
    "container:api": (
        "The reconciliation API: HTTP routes and an MCP tool for operators and agents.",
        "Starts runs from a set of accounts, fetches statements from the bank API with a fan-out and an "
        "unbounded retry, matches them against the ledger (one query per transaction) and classifies "
        "unmatched rows with an LLM in a loop.",
    ),
    "container:worker": (
        "The nightly worker: runs the batch and talks to Pub/Sub.",
        "A Typer CLI and a subscriber start the nightly run; after matching it publishes a run-completed "
        "event and logs a short summary.",
    ),
    "api/recon_api/matching.py": (
        "Pairs bank transactions with ledger entries by reference and amount.",
        "match_batch fetches one ledger entry per transaction (an N+1 pattern flagged io_in_loop) "
        "and pairs it when amounts_equal accepts the amounts, within a 5-cent tolerance.",
    ),
}


def recordings(view: EpochView) -> list[dict[str, Any]]:
    g = view.graph
    recs = []
    for lk in judge.judgeable(view):
        subj = judge.subject(view, lk)
        sl = judge.build_slice(view, lk)
        code_first = sl["code"]["lines"][0][0] if sl["code"]["lines"] else None
        spec_first = sl["spec"]["lines"][0][0] if sl["spec"]["lines"] else None
        if subj.startswith("REQ-003 ->") and "amounts_equal" in subj:
            tol = next(n for n, t in sl["code"]["lines"] if "tolerance_cents = 5" in t)
            out = {
                "verdict": "drift",
                "confidence": 0.93,
                "rationale": (
                    "The spec allows amounts to differ by at most two cents; the code accepts up to 5 cents."
                ),
                "evidence": [
                    {"side": "spec", "start_line": spec_first, "end_line": spec_first, "claim": "two cents"},
                    {"side": "code", "start_line": tol, "end_line": tol, "claim": "tolerance of 5 cents"},
                ],
            }
        elif code_first is not None:
            out = {
                "verdict": "conforms",
                "confidence": 0.9,
                "rationale": "The code does what the spec item states, as far as the slice shows.",
                "evidence": [
                    {
                        "side": "code",
                        "start_line": code_first,
                        "end_line": code_first,
                        "claim": "implementation",
                    }
                ],
            }
        else:
            out = {
                "verdict": "cannot_tell",
                "confidence": 0.5,
                "rationale": "Only an IR digest is available.",
                "evidence": [],
            }
        recs.append({"task": "judge", "subject": subj, "output": out})
    from ad2v.llm import suggest

    for grp in suggest.candidates(view):
        item = g.nodes[grp["item"]]
        names = [g.nodes[c].qualified_name for c, _ in grp["candidates"]]
        subj = f"{item.qualified_name} [{grp['side']}]"
        matches = []
        if item.qualified_name == "CMP-001" and "container:api" in names:
            matches.append(
                {
                    "candidate": f"C{names.index('container:api') + 1}",
                    "verdict": "match",
                    "confidence": 0.86,
                    "rationale": (
                        "The api container serves the HTTP routes and the MCP tool the component describes."
                    ),
                    "evidence": [],
                }
            )
        if item.qualified_name == "CMP-001" and "api/recon_api" in names:
            matches.append(
                {
                    "candidate": f"C{names.index('api/recon_api') + 1}",
                    "verdict": "match",
                    "confidence": 0.8,
                    "rationale": "The api/recon_api package implements the reconciliation API.",
                    "evidence": [],
                }
            )
        recs.append({"task": "suggest", "subject": subj, "output": {"matches": matches}})
    for q, (card, deep) in SUMMARIES.items():
        kind = next(n.kind for n in g.nodes.values() if n.qualified_name == q)
        recs.append(
            {
                "task": "summarize",
                "subject": f"{q} [{kind}]",
                "output": {"card": card, "deep": deep, "mentions": []},
            }
        )
    w = next(w for w in view.derived.workflows if w.name == "POST /v1/reconciliations")
    for k, coarse, _spans in narrate.levels(view, w):
        steps = []
        for i, cs in enumerate(coarse):
            names_ = [g.nodes[n].name for n in cs.node_ids if n in g.nodes]
            steps.append(
                {
                    "step": i,
                    "text": f"{', '.join(names_)} {'handles' if len(names_) == 1 else 'handle'} "
                    f"this part of starting a run (level {k}).",
                    "mentions": [],
                }
            )
        recs.append(
            {
                "task": "narrate",
                "subject": f"{w.workflow_id} containment L{k} C0",
                "output": {"narrations": steps},
            }
        )
    return recs


def main() -> None:
    fx = VIEWER / "tests" / "fixtures"
    gen = VIEWER / "src" / "generated"
    fx.mkdir(parents=True, exist_ok=True)
    gen.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ad2v-viewer-"))
    try:
        sc = Scenario(tmp / "payments-recon").build()
        out = fx / "demo.ad2v"
        if out.exists():
            out.unlink()
        first = sc.commits[0][1]
        gitsource.run_history(sc.repo, f"{first}^!", out, "specs", ["test-results/junit.xml"])
        gitsource.run_history(sc.repo, f"{first}..HEAD", out, "specs", ["test-results/junit.xml"])
        conn = store.open_rw(out)
        with conn:
            for r in store.epoch_rows(conn):
                materialize.materialize(conn, r["epoch_id"])
            layout.ensure(conn)
        head = store.head_epoch(conn)
        view = EpochView(conn, head, from_data({}))
        rec_dir = tmp / "rec"
        rec_dir.mkdir()
        (rec_dir / "demo.json").write_text(json.dumps({"recordings": recordings(view)}), encoding="utf-8")
        conn.close()
        cfg = from_data({"provider": "fake", "fake_replay_dir": str(rec_dir)})
        api.run(
            out,
            cfg,
            ["judge", "suggest", "summarize", "narrate"],
            1.0,
            provider=ReplayOnly(cfg.model, rec_dir),
        )
        conn = store.open_readonly(out)
        try:
            g = store.load_graph(conn, head)
            anc = workflows.ancestry(g)
            from ad2v.materialize import derive

            proj = []
            for w in derive(conn, head).workflows:
                if w.side != "code":
                    continue
                maxd = max((len(anc.get(n, [])) for s in w.steps for n in s.node_ids), default=1)
                by_depth = {}
                for k in range(0, maxd + 1):
                    coarse, spans = workflows.project(w.steps, k, "containment", anc)
                    by_depth[k] = [
                        {"nodeIds": c.node_ids, "touched": c.touched, "span": list(c.span)} for c in coarse
                    ]
                view = EpochView(conn, head, from_data({}))
                lv = [k for k, _c, _s in narrate.levels(view, w)]
                proj.append({"workflowId": w.workflow_id, "name": w.name, "byDepth": by_depth, "levels": lv})
            (fx / "projections.json").write_text(
                json.dumps({"epoch": head, "workflows": proj}, indent=1), encoding="utf-8"
            )
        finally:
            conn.close()
        styles = {
            "statuses": {
                s: {
                    "token": st.token,
                    "line": st.line,
                    "fill": st.fill,
                    "decoration": st.decoration,
                    "weight": st.weight,
                }
                for s, st in tokens.STATUS_STYLES.items()
            },
            "overlays": {
                k: {"glyph": g_, "color": c, "text": t} for k, (g_, c, t) in tokens.OVERLAY_BADGES.items()
            },
            "dasharray": tokens.DASHARRAY,
            "statusOrder": list(ir.NODE_STATUSES),
        }
        (fx / "styles.json").write_text(json.dumps(styles, indent=1), encoding="utf-8")
        data = base64.b64encode(out.read_bytes()).decode("ascii")
        (gen / "demo-data.ts").write_text(
            "// generated by scripts/make_fixtures.py: the payments-recon demo file (base64)\n"
            f'export const DEMO_AD2V_BASE64 = "{data}";\n',
            encoding="utf-8",
        )
        print(f"demo.ad2v {out.stat().st_size} bytes, {len(proj)} workflows, head {head}")
    finally:
        gitsource._rmtree(tmp)


if __name__ == "__main__":
    main()
