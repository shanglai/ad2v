"""Deterministic layout `nestgrid-v1` (format spec §12): nested grid packing on the ground plane.

Every node gets a box `(x, y, z, w, h, d)`: `x, y` on the ground plane (y grows "south"), `z`
the height it stands at, `w, h` its footprint, `d` its own height. Children are packed in a
grid inside their parent; ports sit on the parent's east and south edges; the spec side is a
separate region west of the code side.

**Mental-map stability.** Each parent's grid (track sizes and child slots) is stored in
`layout_grids`. In a new epoch a parent starts from its previous grid (ids mapped through
`id_lineage`): existing children keep their slot, removed ones free it, new children fill free
slots in stable order (kind, qualified name), and the grid only grows by appending a row or a
column. Track sizes are quantized on a geometric scale and never shrink, so an edit deep in the
tree rarely moves anything outside it. No randomness anywhere.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ad2v import ids, ir, store

ALGORITHM = "nestgrid-v1"  # the default
ALGORITHMS = ("nestgrid-v1", "nestgrid-v2")  # v2: shelf packing (P7, ADR-0062), behind a flag
PAD = 0.5  # inner padding of a parent
GAP = 0.3  # between grid tracks
PORT = 0.4  # port notch footprint
PORT_STEP = 0.6  # distance between ports along an edge
HEADROOM = 1.2  # a track that must grow is sized for 20% more than it needs
SPEC_GAP = 8.0  # between the spec region and the code region
TRACKS = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)  # then ×1.25 per step
KIND_ORDER = {k: i for i, k in enumerate(ir.NODE_KINDS)}  # the glyph grammar's kind order
PORT_KINDS = frozenset(ir.PORT_KINDS)
# own height d of a node's box (slabs are thin; leaves stand taller than they are thick)
HEIGHT = {
    "system": 0.2,
    "container": 0.5,
    "component": 0.3,
    "module": 0.2,
    "class": 0.25,
    "function": 0.15,
    "spec_root": 0.2,
    "spec_doc": 0.15,
    "spec_component": 0.15,
}
LEAF_HEIGHT = {"datastore": 1.2, "queue": 0.6, "external_service": 0.9, "llm_endpoint": 0.8, "ui": 0.8}


def quantize(v: float) -> float:
    """The smallest track size ≥ v on the geometric scale."""
    for t in TRACKS:
        if v <= t + 1e-9:
            return t
    t = TRACKS[-1]
    while t < v - 1e-9:  # ×1.25 steps, on a 0.5 grid: at most 25% slack above the scale
        t = math.ceil(t * 1.25 * 2) / 2
    return t


def leaf_side(size_weight: int) -> float:
    """Log-bucketed footprint: big nodes stand out without giant outliers."""
    b = int(math.log2(max(1, size_weight)) // 2)  # 0 for < 4, 1 for < 16, 2 for < 64, ...
    return min(4.0, 1.0 + 0.5 * b)


@dataclass
class Grid:
    cols: list[float] = field(default_factory=list)  # column widths
    rows: list[float] = field(default_factory=list)  # row heights
    slots: dict[str, tuple[int, int]] = field(default_factory=dict)  # child id -> (row, col)
    ports: dict[str, tuple[str, int]] = field(default_factory=dict)  # port id -> ("e" | "s", index)
    # nestgrid-v2 only: per child, its x offset in its shelf and its reserved width; the shelf width
    xoff: dict[str, float] = field(default_factory=dict)
    widths: dict[str, float] = field(default_factory=dict)
    target: float = 0.0

    def to_json(self) -> str:
        d: dict[str, Any] = {
            "cols": self.cols,
            "rows": self.rows,
            "slots": {k: list(v) for k, v in sorted(self.slots.items())},
            "ports": {k: list(v) for k, v in sorted(self.ports.items())},
        }
        if self.widths:
            d["xoff"] = dict(sorted(self.xoff.items()))
            d["widths"] = dict(sorted(self.widths.items()))
            d["target"] = self.target
        return ids.canonical_json(d)

    def edge_len(self, edge: str) -> int:
        return max((i + 1 for e, i in self.ports.values() if e == edge), default=0)

    @staticmethod
    def from_json(s: str) -> Grid:
        d = json.loads(s)
        ports = {k: (v[0], v[1]) for k, v in d.get("ports", {}).items()}
        return Grid(
            list(d["cols"]),
            list(d["rows"]),
            {k: (v[0], v[1]) for k, v in d["slots"].items()},
            ports,
            dict(d.get("xoff", {})),
            dict(d.get("widths", {})),
            float(d.get("target", 0.0)),
        )


@dataclass
class Box:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0
    h: float = 1.0
    d: float = 0.2


def _order(g: ir.Graph, nid: str) -> tuple[int, str]:
    n = g.nodes[nid]
    return (KIND_ORDER.get(n.kind, 99), n.qualified_name)


def assign_ports(ports: list[str], prev: Grid | None, g: ir.Graph) -> dict[str, tuple[str, int]]:
    """Port slots on the east/south edges, persisted; new ports go to the shorter edge."""
    out = {pid: prev.ports[pid] for pid in ports if prev and pid in prev.ports}
    for pid in sorted((q for q in ports if q not in out), key=lambda q: _order(g, q)):
        used = {e: {i for ee, i in out.values() if ee == e} for e in ("e", "s")}
        edge = "e" if len(used["e"]) <= len(used["s"]) else "s"
        idx = next(i for i in range(len(ports) + 1) if i not in used[edge])
        out[pid] = (edge, idx)
    return out


def assign_slots(children: list[str], prev: Grid | None, g: ir.Graph) -> Grid:
    """Slots for a parent's (non-port) children, persisting the previous grid."""
    grid = Grid(list(prev.cols), list(prev.rows), {}) if prev and prev.cols else Grid()
    kept = {c: prev.slots[c] for c in children if prev and c in prev.slots}
    grid.slots.update(kept)
    new = sorted((c for c in children if c not in kept), key=lambda c: _order(g, c))
    if not grid.cols:  # first layout of this parent: a near-square grid
        n = len(new)
        cols = max(1, math.ceil(math.sqrt(n)))
        rows = max(1, math.ceil(n / cols)) if n else 1
        grid.cols, grid.rows = [0.0] * cols, [0.0] * rows
    taken = set(grid.slots.values())
    free = [(r, c) for r in range(len(grid.rows)) for c in range(len(grid.cols)) if (r, c) not in taken]
    for child in new:
        if not free:  # grow: append a row or a column, never move anyone
            if len(grid.cols) <= len(grid.rows):
                grid.cols.append(0.0)
                free = [(r, len(grid.cols) - 1) for r in range(len(grid.rows))]
            else:
                grid.rows.append(0.0)
                free = [(len(grid.rows) - 1, c) for c in range(len(grid.cols))]
        slot = free.pop(0)
        grid.slots[child] = slot
    return grid


# P9 (ADR-0072): kinds that stay in the graph but get no box on the map (shown in their parent's card)
OFF_MAP_KINDS = frozenset({"scenario_step"})


def map_children(g: ir.Graph) -> dict[str, list[str]]:
    return {
        k: [c for c in v if g.nodes[c].kind not in OFF_MAP_KINDS]
        for k, v in g.children().items()
        if g.nodes[k].kind not in OFF_MAP_KINDS
    }


class Layouter:
    def __init__(self, g: ir.Graph, glyph_sizes: dict[str, int], prev_grids: dict[str, Grid]) -> None:
        self.g = g
        self.sizes = glyph_sizes
        self.prev = prev_grids  # already mapped to this epoch's ids
        self.kids = map_children(g)
        self.grids: dict[str, Grid] = {}
        self.boxes: dict[str, Box] = {}

    def children(self, nid: str) -> tuple[list[str], list[str]]:
        kids = sorted(self.kids.get(nid, []))
        ports = sorted(
            (c for c in kids if self.g.nodes[c].kind in PORT_KINDS), key=lambda c: _order(self.g, c)
        )
        return [c for c in kids if self.g.nodes[c].kind not in PORT_KINDS], ports

    def measure(self, nid: str) -> tuple[float, float]:
        """Footprint (w, h), bottom-up; fixes the parent's grid tracks."""
        inner, ports = self.children(nid)
        n = self.g.nodes[nid]
        prev = self.prev.get(nid)
        if not inner:
            s = leaf_side(self.sizes.get(nid, 1))
            w = h = s
            grid = Grid()
        else:
            grid = assign_slots(inner, prev, self.g)
            need_c = [0.0] * len(grid.cols)
            need_r = [0.0] * len(grid.rows)
            for c in inner:
                cw, ch = self.measure(c)
                r, k = grid.slots[c]
                need_c[k] = max(need_c[k], cw)
                need_r[r] = max(need_r[r], ch)
            # a track grows only past its size, then with headroom: small growth stays inside it
            grid.cols = [
                old if v <= old else quantize(v * HEADROOM) for old, v in zip(grid.cols, need_c, strict=True)
            ]
            grid.rows = [
                old if v <= old else quantize(v * HEADROOM) for old, v in zip(grid.rows, need_r, strict=True)
            ]
            grid.cols = [c or 1.0 for c in grid.cols]
            grid.rows = [r or 1.0 for r in grid.rows]
            w = 2 * PAD + sum(grid.cols) + GAP * (len(grid.cols) - 1)
            h = 2 * PAD + sum(grid.rows) + GAP * (len(grid.rows) - 1)
        if ports:  # persisted slots on the east and south edges; edges long enough for them
            grid.ports = assign_ports(ports, prev, self.g)
            h = max(h, PORT_STEP * grid.edge_len("e") + PAD)
            w = max(w, PORT_STEP * grid.edge_len("s") + PAD)
        if inner or ports:
            self.grids[nid] = grid
        self.boxes[nid] = Box(w=round(w, 4), h=round(h, 4), d=self._height(n, bool(inner)))
        return self.boxes[nid].w, self.boxes[nid].h

    def _height(self, n: ir.Node, has_kids: bool) -> float:
        if n.kind in HEIGHT:
            return HEIGHT[n.kind]
        if n.kind in LEAF_HEIGHT:
            return LEAF_HEIGHT[n.kind]
        if n.kind in PORT_KINDS:
            return 0.3
        return 0.15 if has_kids else 0.4

    def place(self, nid: str, x: float, y: float, z: float) -> None:
        b = self.boxes[nid]
        b.x, b.y, b.z = round(x, 4), round(y, 4), round(z, 4)
        inner, ports = self.children(nid)
        top = z + b.d
        if inner:
            grid = self.grids[nid]
            col_x = [x + PAD + sum(grid.cols[:k]) + GAP * k for k in range(len(grid.cols))]
            row_y = [y + PAD + sum(grid.rows[:r]) + GAP * r for r in range(len(grid.rows))]
            for c in inner:
                r, k = grid.slots[c]
                self.place(c, col_x[k], row_y[r], top)
        slots = self.grids[nid].ports if ports else {}
        for p in ports:
            pb = self.boxes.setdefault(p, Box())
            pb.w = pb.h = PORT
            pb.d = 0.3
            edge, i = slots[p]
            if edge == "e":  # on the east edge, centred on the boundary line
                pb.x, pb.y = round(x + b.w - PORT / 2, 4), round(y + PAD / 2 + PORT_STEP * i, 4)
            else:
                pb.x, pb.y = round(x + PAD / 2 + PORT_STEP * i, 4), round(y + b.h - PORT / 2, 4)
            pb.z = round(z, 4)
            self.boxes[p] = pb

    def run(self) -> dict[str, Box]:
        roots = sorted(
            (n for n in self.g.nodes.values() if n.parent_id is None), key=lambda n: _order(self.g, n.id)
        )
        code = [r for r in roots if r.side == "code"]
        spec = [r for r in roots if r.side == "spec"]
        x = 0.0
        for r in code:  # code region from x = 0 eastwards
            w, _ = self.measure(r.id)
            self.place(r.id, x, 0.0, 0.0)
            x += w + SPEC_GAP
        x = 0.0
        for r in spec:  # spec region west of the code, separated by SPEC_GAP
            w, _ = self.measure(r.id)
            x -= w + SPEC_GAP
            self.place(r.id, x, 0.0, 0.0)
        return self.boxes


# -- nestgrid-v2: shelf packing (P7, ADR-0062) ---------------------------------------------------
def assign_shelves(
    children: list[str], sizes: dict[str, tuple[float, float]], prev: Grid | None, g: ir.Graph
) -> Grid:
    """Shelves for a parent's (non-port) children with v1's persistence rule: a child keeps its
    shelf and x offset while it fits its reserved width (quantized with headroom, never shrinking);
    removed children free their interval; new children fill a free interval, then the end of a
    shelf within the target width, then a new shelf. A child that outgrows its interval moves
    alone; nobody else does."""
    grid = Grid()
    grid.target = prev.target if prev and prev.target else 0.0
    grid.rows = list(prev.rows) if prev and prev.widths else []
    keep: list[str] = []
    for c in children:
        if prev and c in prev.widths and c in prev.slots:
            need = sizes[c][0]
            if need <= prev.widths[c] + 1e-9:
                keep.append(c)
                grid.slots[c] = prev.slots[c]
                grid.xoff[c] = prev.xoff[c]
                grid.widths[c] = prev.widths[c]
    new = sorted((c for c in children if c not in grid.slots), key=lambda c: _order(g, c))
    res = {c: quantize(sizes[c][0] * HEADROOM) for c in new}
    if not grid.target:  # first layout: shelves about as wide as a square of the children's area
        area = sum(res[c] * quantize(sizes[c][1] * HEADROOM) for c in new)
        grid.target = round(max([*res.values(), math.sqrt(area) * 1.15, 1.0]), 4)

    def used(shelf: int) -> list[tuple[float, float]]:
        return sorted(
            (grid.xoff[c], grid.xoff[c] + grid.widths[c]) for c, (s, _) in grid.slots.items() if s == shelf
        )

    for c in new:
        w = res[c]
        placed = False
        for shelf in range(len(grid.rows)):
            x = 0.0
            for a, b in used(shelf) + [(max(grid.target, w) + GAP + 1e9, 0.0)]:
                if a - x >= w + GAP - 1e-9 and x + w <= max(grid.target, w) + 1e-9:
                    grid.slots[c], grid.xoff[c], grid.widths[c] = (shelf, 0), round(x, 4), w
                    placed = True
                    break
                x = max(x, b + GAP)
            if placed:
                break
        if not placed:
            grid.rows.append(0.0)
            grid.slots[c], grid.xoff[c], grid.widths[c] = (len(grid.rows) - 1, 0), 0.0, w
    return grid


class ShelfLayouter(Layouter):
    """nestgrid-v2: same ports, heights and roots as v1; children packed on shelves."""

    def measure(self, nid: str) -> tuple[float, float]:
        inner, ports = self.children(nid)
        n = self.g.nodes[nid]
        prev = self.prev.get(nid)
        if not inner:
            s = leaf_side(self.sizes.get(nid, 1))
            w = h = s
            grid = Grid()
        else:
            sizes = {c: self.measure(c) for c in inner}
            grid = assign_shelves(inner, sizes, prev, self.g)
            need = [0.0] * len(grid.rows)
            for c in inner:
                need[grid.slots[c][0]] = max(need[grid.slots[c][0]], sizes[c][1])
            grid.rows = [
                old if v <= old else quantize(v * HEADROOM) for old, v in zip(grid.rows, need, strict=True)
            ]
            grid.rows = [r or 1.0 for r in grid.rows]
            used = max((grid.xoff[c] + grid.widths[c] for c in inner), default=1.0)
            w = 2 * PAD + used
            h = 2 * PAD + sum(grid.rows) + GAP * (len(grid.rows) - 1)
        if ports:
            grid.ports = assign_ports(ports, prev, self.g)
            h = max(h, PORT_STEP * grid.edge_len("e") + PAD)
            w = max(w, PORT_STEP * grid.edge_len("s") + PAD)
        if inner or ports:
            self.grids[nid] = grid
        self.boxes[nid] = Box(w=round(w, 4), h=round(h, 4), d=self._height(n, bool(inner)))
        return self.boxes[nid].w, self.boxes[nid].h

    def place(self, nid: str, x: float, y: float, z: float) -> None:
        b = self.boxes[nid]
        b.x, b.y, b.z = round(x, 4), round(y, 4), round(z, 4)
        inner, ports = self.children(nid)
        top = z + b.d
        if inner:
            grid = self.grids[nid]
            row_y = [y + PAD + sum(grid.rows[:r]) + GAP * r for r in range(len(grid.rows))]
            for c in inner:
                self.place(c, x + PAD + grid.xoff[c], row_y[grid.slots[c][0]], top)
        if ports:
            self._place_ports(nid, x, y, z, ports)

    def _place_ports(self, nid: str, x: float, y: float, z: float, ports: list[str]) -> None:
        b, slots = self.boxes[nid], self.grids[nid].ports
        for p in ports:
            pb = self.boxes.setdefault(p, Box())
            pb.w = pb.h = PORT
            pb.d = 0.3
            edge, i = slots[p]
            if edge == "e":
                pb.x, pb.y = round(x + b.w - PORT / 2, 4), round(y + PAD / 2 + PORT_STEP * i, 4)
            else:
                pb.x, pb.y = round(x + PAD / 2 + PORT_STEP * i, 4), round(y + b.h - PORT / 2, 4)
            pb.z = round(z, 4)
            self.boxes[p] = pb


def density(g: ir.Graph, boxes: dict[str, Box]) -> dict[str, float]:
    """Occupied / parent area: the children's footprints over the parents' inner areas, summed over
    every parent with children (area-weighted), and at the top level only (the system's children)."""
    kids = map_children(g)
    occ = tot = top_occ = top_tot = 0.0
    for pid, cs in kids.items():
        inner = [c for c in cs if c in boxes and g.nodes[c].kind not in PORT_KINDS]
        if not inner or pid not in boxes:
            continue
        pb = boxes[pid]
        a = max(1e-9, (pb.w - 2 * PAD) * (pb.h - 2 * PAD))
        o = sum(boxes[c].w * boxes[c].h for c in inner)
        occ, tot = occ + o, tot + a
        if g.nodes[pid].parent_id is None:
            top_occ, top_tot = top_occ + o, top_tot + a
    return {
        "all": round(occ / tot, 4) if tot else 0.0,
        "top": round(top_occ / top_tot, 4) if top_tot else 0.0,
    }


# -- storage ------------------------------------------------------------------------------------
# The same table as in schema/ad2v-v0.6.sql, for v0.4 files created before P5 (additive).
DDL = """
CREATE TABLE IF NOT EXISTS layout_grids (
    epoch_id  TEXT NOT NULL REFERENCES epochs(epoch_id),
    node_id   TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    grid_json TEXT NOT NULL,
    PRIMARY KEY (epoch_id, node_id, algorithm)
);
"""


def has_layout(conn: sqlite3.Connection, epoch_id: str, algorithm: str = ALGORITHM) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM layout WHERE epoch_id = ? AND algorithm = ? LIMIT 1", (epoch_id, algorithm)
        ).fetchone()
        is not None
    )


def _prev_grids(conn: sqlite3.Connection, epoch_id: str, algorithm: str = ALGORITHM) -> dict[str, Grid]:
    """The parent epoch's grids with ids mapped through this epoch's lineage."""
    ep = store.get_epoch(conn, epoch_id)
    if ep.parent_epoch_id is None:
        return {}
    rows = conn.execute(
        "SELECT node_id, grid_json FROM layout_grids WHERE epoch_id = ? AND algorithm = ?",
        (ep.parent_epoch_id, algorithm),
    ).fetchall()
    fwd = {o: n for o, n, m, _ in store.load_lineage(conn, epoch_id) if m != "ambiguous"}
    out = {}
    for nid, gj in rows:
        g = Grid.from_json(gj)
        g.slots = {fwd.get(c, c): s for c, s in g.slots.items()}
        g.xoff = {fwd.get(c, c): v for c, v in g.xoff.items()}
        g.widths = {fwd.get(c, c): v for c, v in g.widths.items()}
        out[fwd.get(nid, nid)] = g
    return out


def compute(
    conn: sqlite3.Connection, epoch_id: str, algorithm: str = ALGORITHM
) -> tuple[dict[str, Box], dict[str, Grid]]:
    g = store.load_graph(conn, epoch_id)
    from ad2v import glyphs

    sizes = {gl.node_id: gl.size_weight for gl in glyphs.compute(g)}
    cls = ShelfLayouter if algorithm == "nestgrid-v2" else Layouter
    lay = cls(g, sizes, _prev_grids(conn, epoch_id, algorithm))
    boxes = lay.run()
    return boxes, lay.grids


def write(conn: sqlite3.Connection, epoch_id: str, algorithm: str = ALGORITHM) -> int:
    """Compute and store the layout of one epoch (replacing an existing one). Returns rows."""
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unknown layout algorithm {algorithm!r} (known: {', '.join(ALGORITHMS)})")
    boxes, grids = compute(conn, epoch_id, algorithm)
    conn.execute("DELETE FROM layout WHERE epoch_id = ? AND algorithm = ?", (epoch_id, algorithm))
    conn.execute("DELETE FROM layout_grids WHERE epoch_id = ? AND algorithm = ?", (epoch_id, algorithm))
    conn.executemany(
        "INSERT INTO layout(epoch_id, node_id, lod, algorithm, x, y, z, w, h, d)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(epoch_id, nid, 0, algorithm, b.x, b.y, b.z, b.w, b.h, b.d) for nid, b in sorted(boxes.items())],
    )
    conn.executemany(
        "INSERT INTO layout_grids VALUES (?,?,?,?)",
        [(epoch_id, nid, algorithm, gr.to_json()) for nid, gr in sorted(grids.items())],
    )
    return len(boxes)


def ensure(
    conn: sqlite3.Connection, epoch_ids: list[str] | None = None, algorithm: str = ALGORITHM
) -> list[str]:
    """Lay out every epoch (or the given ones, with their missing ancestors first) lacking a layout."""
    rows = store.epoch_rows(conn)
    wanted = set(epoch_ids) if epoch_ids is not None else {r["epoch_id"] for r in rows}
    done = []
    for r in rows:  # oldest first: each epoch inherits its parent's grids
        e = r["epoch_id"]
        needed = e in wanted or any(w for w in wanted if _is_ancestor(conn, e, w))
        if needed and not has_layout(conn, e, algorithm):
            write(conn, e, algorithm)
            done.append(e)
    return done


def _is_ancestor(conn: sqlite3.Connection, a: str, b: str) -> bool:
    cur = store.get_epoch_or_none(conn, b)
    while cur is not None and cur.parent_epoch_id is not None:
        if cur.parent_epoch_id == a:
            return True
        cur = store.get_epoch_or_none(conn, cur.parent_epoch_id)
    return False


def load(conn: sqlite3.Connection, epoch_id: str, algorithm: str = ALGORITHM) -> dict[str, dict[str, Any]]:
    return {
        r["node_id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM layout WHERE epoch_id = ? AND algorithm = ?", (epoch_id, algorithm)
        )
    }
