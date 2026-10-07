"""P5 M1: deterministic layout nestgrid-v1: determinism, stability over history, geometry invariants."""

import shutil

import pytest
from history_scenario import Scenario, git_available

from ad2v import gitsource, ids, ir, layout, pipeline, store
from ad2v.cli import main

from helpers import FIXTURE, JUNIT

EPS = 1e-6


def _rows(path):
    conn = store.open_readonly(path)
    try:
        return [tuple(r) for r in conn.execute("SELECT * FROM layout ORDER BY epoch_id, node_id")]
    finally:
        conn.close()


def _head(path):
    conn = store.open_readonly(path)
    try:
        e = store.head_epoch(conn)
        return store.load_graph(conn, e), layout.load(conn, e)
    finally:
        conn.close()


def test_layout_is_deterministic_and_crlf_invariant(tmp_path):
    a, b = tmp_path / "a.ad2v", tmp_path / "b.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", a, test_results=[JUNIT])
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", b, test_results=[JUNIT])
    assert _rows(a) == _rows(b) and len(_rows(a)) > 100
    crlf = tmp_path / "crlf"
    shutil.copytree(FIXTURE, crlf)
    for p in crlf.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".md", ".yaml", ".feature", ".xml"):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    c = tmp_path / "c.ad2v"
    pipeline.extract_to_file(crlf, crlf / "specs", c, test_results=[crlf / "test-results" / "junit.xml"])
    assert _rows(c) == _rows(a)


def _with(path, algorithm: str):  # noqa: ANN001, ANN202
    """Lay out every epoch with `algorithm` (v1 is already there) and return the head's graph + boxes."""
    if algorithm != layout.ALGORITHM:
        conn = store.open_rw(path)
        try:
            with conn:
                layout.ensure(conn, None, algorithm)
        finally:
            conn.close()
    conn = store.open_readonly(path)
    try:
        head = store.resolve_epoch(conn, "head")
        return store.load_graph(conn, head), layout.load(conn, head, algorithm)
    finally:
        conn.close()


@pytest.mark.parametrize("algorithm", layout.ALGORITHMS)
def test_geometry_invariants(algorithm):
    g, L = _with(_fixture_file(), algorithm)
    assert set(L) == {n for n, v in g.nodes.items() if v.kind not in layout.OFF_MAP_KINDS}
    kids = layout.map_children(g)
    for pid, cs in kids.items():
        p = L[pid]
        inner = [c for c in cs if g.nodes[c].kind not in layout.PORT_KINDS]
        for c in inner:  # children inside their parent, standing on it
            b = L[c]
            assert p["x"] - EPS <= b["x"] and b["x"] + b["w"] <= p["x"] + p["w"] + EPS, (pid, c)
            assert p["y"] - EPS <= b["y"] and b["y"] + b["h"] <= p["y"] + p["h"] + EPS, (pid, c)
            assert b["z"] == pytest.approx(p["z"] + p["d"])
        for i, a in enumerate(inner):  # no overlaps among siblings
            for c in inner[i + 1 :]:
                A, B = L[a], L[c]
                overlap = (
                    A["x"] < B["x"] + B["w"] - EPS
                    and B["x"] < A["x"] + A["w"] - EPS
                    and A["y"] < B["y"] + B["h"] - EPS
                    and B["y"] < A["y"] + A["h"] - EPS
                )
                assert not overlap, (a, c)
        for c in cs:  # ports sit on the east or south boundary line
            if g.nodes[c].kind in layout.PORT_KINDS:
                b = L[c]
                cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
                on_east = abs(cx - (p["x"] + p["w"])) < EPS and p["y"] <= cy <= p["y"] + p["h"]
                on_south = abs(cy - (p["y"] + p["h"])) < EPS and p["x"] <= cx <= p["x"] + p["w"]
                assert on_east or on_south, c
    code = [b for n, b in L.items() if g.nodes[n].side == "code"]
    spec = [b for n, b in L.items() if g.nodes[n].side == "spec"]
    assert max(b["x"] + b["w"] for b in spec) < min(b["x"] for b in code)  # spec region is west


_FILE = []


def _fixture_file():
    if not _FILE:
        import tempfile
        from pathlib import Path

        out = Path(tempfile.mkdtemp()) / "f.ad2v"
        pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, test_results=[JUNIT])
        _FILE.append(out)
    return _FILE[0]


def test_quantize_and_slots():
    assert [layout.quantize(v) for v in (0.2, 1.2, 5, 16, 17, 21)] == [1.0, 1.5, 6.0, 16.0, 20.0, 25.0]
    assert layout.leaf_side(1) == 1.0 and layout.leaf_side(20) == 2.0 and layout.leaf_side(10**6) == 4.0


@pytest.mark.skipif(not git_available(), reason="needs git")
@pytest.mark.parametrize("algorithm", layout.ALGORITHMS)
def test_stability_over_history(tmp_path, algorithm):
    sc = Scenario(tmp_path / "payments-recon").build()
    out = tmp_path / "h.ad2v"
    first = sc.commits[0][1]
    gitsource.run_history(sc.repo, f"{first}^!", out, "specs", ["test-results/junit.xml"])
    gitsource.run_history(sc.repo, f"{first}..HEAD", out, "specs", ["test-results/junit.xml"])
    if algorithm != layout.ALGORITHM:
        c = store.open_rw(out)
        with c:
            layout.ensure(c, None, algorithm)
        c.close()
    conn = store.open_readonly(out)
    kept = total = 0
    renamed_ok = []
    try:
        eps = [r["epoch_id"] for r in store.epoch_rows(conn)]
        for a, b in zip(eps, eps[1:], strict=False):
            ga, gb = store.load_graph(conn, a), store.load_graph(conn, b)
            La, Lb = layout.load(conn, a, algorithm), layout.load(conn, b, algorithm)
            fwd = {o: n for o, n, m, _ in store.load_lineage(conn, b) if m != "ambiguous"}
            for old, n in ga.nodes.items():
                new = fwd.get(old, old)
                if new not in gb.nodes or n.kind in layout.OFF_MAP_KINDS:
                    continue
                if old in fwd:  # renamed: keeps its slot (same position)
                    renamed_ok.append((La[old]["x"], La[old]["y"]) == (Lb[new]["x"], Lb[new]["y"]))
                if gb.nodes[new].subtree_hash == n.subtree_hash or old in fwd:
                    total += 1
                    kept += (La[old]["x"], La[old]["y"], La[old]["z"]) == (
                        Lb[new]["x"],
                        Lb[new]["y"],
                        Lb[new]["z"],
                    )
    finally:
        conn.close()
    rate = kept / total
    print(f"layout stability ({algorithm}): {kept}/{total} = {rate:.4f} unchanged nodes keep their position")
    assert rate >= 0.95
    assert renamed_ok and all(renamed_ok)


def test_layout_cli_and_materialize_last(tmp_path, capsys):
    out = tmp_path / "x.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", out, test_results=[JUNIT])
    conn = store.open_rw(out)
    with conn:
        conn.execute("DELETE FROM layout")
        conn.execute("DELETE FROM layout_grids")
    conn.close()
    assert main(["layout", str(out)]) == 0
    assert "laid out 1 epoch" in capsys.readouterr().out
    assert main(["layout", str(out)]) == 0
    assert "up to date" in capsys.readouterr().out
    assert main(["materialize", str(out), "--epochs", "last:3"]) == 0
    assert "materialized" in capsys.readouterr().out


def test_v2_packs_denser_and_reuses_freed_intervals():
    g, L1 = _with(_fixture_file(), "nestgrid-v1")
    _, L2 = _with(_fixture_file(), "nestgrid-v2")
    box = lambda L: {k: layout.Box(v["x"], v["y"], v["z"], v["w"], v["h"], v["d"]) for k, v in L.items()}  # noqa: E731
    d1, d2 = layout.density(g, box(L1)), layout.density(g, box(L2))
    assert 0 < d1["all"] <= 1 and 0 < d2["all"] <= 1
    print(f"density v1 {d1} v2 {d2}")
    # shelf persistence: a removed child frees its interval and a new child of the same size takes it
    gg = ir.Graph()
    for q in ("p", "p/a", "p/b", "p/c", "p/d"):
        parent = None if q == "p" else ids.node_id("code", "module", "p")
        gg.add_node(ir.Node("code", "module", q.split("/")[-1], q, parent_id=parent))
    a, b, c = (ids.node_id("code", "module", f"p/{x}") for x in "abc")
    sizes = {a: (1.0, 1.0), b: (1.0, 1.0), c: (1.0, 1.0)}
    g1 = layout.assign_shelves([a, b, c], sizes, None, gg)
    d = ids.node_id("code", "module", "p/d")
    g2 = layout.assign_shelves([a, c, d], {**sizes, d: (1.0, 1.0)}, g1, gg)
    assert g2.slots[a] == g1.slots[a] and g2.xoff[a] == g1.xoff[a] and g2.xoff[c] == g1.xoff[c]
    assert (g2.slots[d], g2.xoff[d]) == (g1.slots[b], g1.xoff[b])  # d took b's freed place
    g3 = layout.assign_shelves([a, c], {a: (9.0, 1.0), c: (1.0, 1.0)}, g1, gg)
    assert g3.xoff[c] == g1.xoff[c] and g3.widths[a] >= 9.0  # a grew: only a moved
