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


def _check_invariants(steps, k):
    coarse, spans = workflows.project(steps, k)
    assert len(coarse) == len(spans)
    # spans partition the trace and are contiguous, in order
    covered = []
    for a, b in spans:
        assert a <= b
        covered.extend(range(a, b + 1))
    assert covered == [s.seq for s in steps]
    for c, (a, b) in zip(coarse, spans, strict=True):
        assert c.span == (a, b)
        members = steps[a : b + 1]
        # every member other than the anchor is deeper than k
        assert all(s.depth > k for s in members[1:])
        # the anchor is shallow, unless this is the leading group
        assert members[0].depth <= k or a == 0
        assert set(c.node_ids) <= set(c.touched)
        assert c.touched == list(dict.fromkeys(n for s in members for n in s.node_ids))
    return coarse


def test_projection_invariants_randomized():
    rng = random.Random(SEED)
    for _ in range(500):
        n = rng.randint(1, 60)
        depths = _dfs_depths(rng, n) if rng.random() < 0.7 else [rng.randint(0, 8) for _ in range(n)]
        steps = _steps(depths)
        previous = None
        for k in range(0, max(depths) + 2):
            coarse = _check_invariants(steps, k)
            if previous is not None:
                assert len(coarse) >= previous  # more detail never merges steps
            previous = len(coarse)
        # at k >= max depth the projection is the identity
        coarse, spans = workflows.project(steps, max(depths))
        assert spans == [(i, i) for i in range(n)]


def test_projection_examples():
    steps = _steps([0, 1, 2, 3, 2, 1, 2])
    coarse, spans = workflows.project(steps, 1)
    assert spans == [(0, 0), (1, 4), (5, 6)]
    assert coarse[1].node_ids == ["n1"] and coarse[1].touched == ["n1", "n2", "n3", "n4"]
    _, spans0 = workflows.project(steps, 0)
    assert spans0 == [(0, 6)]
    _, lead = workflows.project(_steps([3, 3, 1, 2]), 1)
    assert lead == [(0, 1), (2, 3)]
    assert workflows.project([], 2) == ([], [])
    with pytest.raises(ValueError):
        workflows.project(steps, -1)


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
