"""Workflow traces and the projection invariant.

`hypothesis` is MPL-2.0 (copyleft, weak), so property tests use a seeded PRNG instead (ADR-0002).
"""

import random

import pytest

from ad2v import ir, workflows
from ad2v.extract.code.base import CodeFacts, Event
from ad2v.manifest import Config

from helpers import node, run_code

SEED = 987654


def _steps(depths):
    return [ir.WorkflowStep(i, [f"n{i}"], d) for i, d in enumerate(depths)]


def _dfs_depths(rng, n):
    depths = [0]
    for _ in range(n - 1):
        depths.append(rng.randint(1, depths[-1] + 1))
    return depths


def _partition(steps, coarse, spans):
    assert len(coarse) == len(spans)
    covered = []  # spans partition the trace and are contiguous, in order
    for a, b in spans:
        assert a <= b
        covered.extend(range(a, b + 1))
    assert covered == [s.seq for s in steps]
    for c, (a, b) in zip(coarse, spans, strict=True):
        assert c.span == (a, b)
        members = steps[a : b + 1]
        assert c.touched == list(dict.fromkeys(n for s in members for n in s.node_ids))


def _check_call_depth(steps, k):
    coarse, spans = workflows.project(steps, k, mode="call_depth")
    _partition(steps, coarse, spans)
    for c, (a, b) in zip(coarse, spans, strict=True):
        members = steps[a : b + 1]
        assert all(s.depth > k for s in members[1:])  # every member other than the anchor is deeper
        assert members[0].depth <= k or a == 0  # anchor is shallow, unless leading group
        assert set(c.node_ids) <= set(c.touched)
    return coarse


def test_projection_call_depth_randomized():
    rng = random.Random(SEED)
    for _ in range(500):
        n = rng.randint(1, 60)
        depths = _dfs_depths(rng, n) if rng.random() < 0.7 else [rng.randint(0, 8) for _ in range(n)]
        steps = _steps(depths)
        previous = None
        for k in range(0, max(depths) + 2):
            coarse = _check_call_depth(steps, k)
            if previous is not None:
                assert len(coarse) >= previous  # more detail never merges steps
            previous = len(coarse)
        coarse, spans = workflows.project(steps, max(depths), mode="call_depth")
        assert spans == [(i, i) for i in range(n)]  # identity at full depth


def _random_tree(rng, size):
    """Random containment tree: ancestry {node: [root, ..., node]}."""
    anc = {"r": ["r"]}
    names = ["r"]
    for i in range(size):
        parent = rng.choice(names)
        nid = f"t{i}"
        anc[nid] = anc[parent] + [nid]
        names.append(nid)
    return anc


def test_projection_containment_randomized():
    rng = random.Random(SEED)
    for _ in range(300):
        anc = _random_tree(rng, rng.randint(1, 40))
        pool = sorted(anc)
        n = rng.randint(1, 50)
        steps = [
            ir.WorkflowStep(i, rng.sample(pool, rng.randint(1, min(3, len(pool)))), rng.randint(0, 6))
            for i in range(n)
        ]
        max_depth = max(len(c) for c in anc.values())
        previous = None
        for k in range(0, max_depth + 1):
            coarse, spans = workflows.project(steps, k, mode="containment", ancestry_map=anc)
            _partition(steps, coarse, spans)
            for c, (a, b) in zip(coarse, spans, strict=True):
                # the coarse step lights up exactly the depth-k ancestors of its members (what is on screen)
                for st in steps[a : b + 1]:
                    key = list(dict.fromkeys(anc[x][min(k, len(anc[x]) - 1)] for x in st.node_ids))
                    assert key == c.node_ids
                assert c.depth == k
            for left, right in zip(coarse, coarse[1:], strict=False):
                assert left.node_ids != right.node_ids  # maximal runs: neighbours differ
            if previous is not None:
                assert len(coarse) >= previous  # zooming in never merges steps
            previous = len(coarse)


def test_projection_examples():
    steps = _steps([0, 1, 2, 3, 2, 1, 2])
    coarse, spans = workflows.project(steps, 1, mode="call_depth")
    assert spans == [(0, 0), (1, 4), (5, 6)]
    assert coarse[1].node_ids == ["n1"] and coarse[1].touched == ["n1", "n2", "n3", "n4"]
    _, spans0 = workflows.project(steps, 0, mode="call_depth")
    assert spans0 == [(0, 6)]
    _, lead = workflows.project(_steps([3, 3, 1, 2]), 1, mode="call_depth")
    assert lead == [(0, 1), (2, 3)]
    assert workflows.project([], 2, mode="call_depth") == ([], [])
    with pytest.raises(ValueError):
        workflows.project(steps, -1, mode="call_depth")
    with pytest.raises(ValueError):
        workflows.project(steps, 1)  # containment (default) needs the ancestry map
    with pytest.raises(ValueError):
        workflows.project(steps, 1, mode="sideways", ancestry_map={})


def test_projection_containment_example():
    anc = {
        "sys": ["sys"],
        "api": ["sys", "api"],
        "worker": ["sys", "worker"],
        "a.py": ["sys", "api", "a.py"],
        "f": ["sys", "api", "a.py", "f"],
        "g": ["sys", "api", "a.py", "g"],
        "w.py": ["sys", "worker", "w.py"],
        "h": ["sys", "worker", "w.py", "h"],
        "db": ["sys", "db"],
    }
    steps = [
        ir.WorkflowStep(0, ["f"], 1),
        ir.WorkflowStep(1, ["g"], 2),
        ir.WorkflowStep(2, ["db"], 3),
        ir.WorkflowStep(3, ["h"], 2),
        ir.WorkflowStep(4, ["f"], 1),
    ]
    coarse, spans = workflows.project(steps, 1, ancestry_map=anc)
    assert [c.node_ids for c in coarse] == [["api"], ["db"], ["worker"], ["api"]]
    assert spans == [(0, 1), (2, 2), (3, 3), (4, 4)]
    coarse0, spans0 = workflows.project(steps, 0, ancestry_map=anc)
    assert spans0 == [(0, 4)] and coarse0[0].node_ids == ["sys"]


def test_ancestry_and_step_nodes():
    g = ir.Graph()
    root = g.add_node(ir.Node("code", "system", "s", "s"))
    mod = g.add_node(ir.Node("code", "module", "m", "m", parent_id=root.id))
    anc = workflows.ancestry(g)
    assert anc[mod.id] == [root.id, mod.id] and anc[root.id] == [root.id]
    wf = ir.Workflow("w", "code", root.id, "static", [ir.WorkflowStep(0, [root.id, mod.id], 0)])
    assert workflows.step_nodes([wf]) == sorted([(wf.workflow_id, 0, root.id), (wf.workflow_id, 0, mod.id)])


def _facts():
    f = CodeFacts()
    f.events = {
        "h": [
            Event("call", ("a",), ("loop",), 1),
            Event("touch", ("db",), (), 2),
            Event("call", ("b", "c"), ("fo",), 3),
        ],
        "a": [Event("call", ("h",), (), 1)],  # cycle back to the handler
        "b": [Event("call", ("d",), (), 1)],
        "d": [Event("call", ("e",), (), 1)],
    }
    f.wrappers = {"b": ["retry"]}
    return f


def test_trace_order_parallel_wrappers_and_cycles():
    steps, truncated = workflows.trace_port(ir.Graph(), _facts(), "port", "h", max_depth=12, max_steps=100)
    assert not truncated
    got = [(s.node_ids, s.depth) for s in steps]
    assert got == [
        (["port"], 0),
        (["h"], 1),
        (["loop", "a"], 2),
        (["h"], 3),  # cycle: emitted, not expanded
        (["db"], 2),
        (["fo", "retry", "b", "c"], 2),  # parallel targets light up together
        (["d"], 3),
        (["e"], 4),
    ]
    assert [s.seq for s in steps] == list(range(len(steps)))


def test_trace_depth_and_step_limits():
    steps, _ = workflows.trace_port(ir.Graph(), _facts(), "port", "h", max_depth=3, max_steps=100)
    assert max(s.depth for s in steps) == 3 and ["e"] not in [s.node_ids for s in steps]
    steps, truncated = workflows.trace_port(ir.Graph(), _facts(), "port", "h", max_depth=12, max_steps=4)
    assert truncated and len(steps) == 4


def test_workflows_from_code_and_scenarios(tmp_path):
    g, facts = run_code(
        tmp_path,
        {
            "app.py": """
            import typer
            app = typer.Typer()

            @app.command()
            def go():
                helper()

            def helper():
                pass
        """,
        },
    )
    wfs = workflows.build_all(g, facts, Config())
    assert len(wfs) == 1
    port = node(g, "cli_command", "cli:sys:go")
    assert wfs[0].entry_node_id == port.id and wfs[0].source == "static"
    assert [s.node_ids for s in wfs[0].steps] == [
        [port.id],
        [node(g, "function", "app.py::go").id],
        [node(g, "function", "app.py::helper").id],
    ]
