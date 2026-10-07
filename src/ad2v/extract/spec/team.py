"""Team SDD formats (P9, ADR-0069): requirement tables and user stories, in Spanish or English.

Both are presets behind the ADR-0048 mechanism (auto-selected by shape, or named in
`spec_markdown:` rules) and both are deterministic. No prose interpretation.

`table`: a Markdown table whose header has an id column (`ID`, `Id`, `Clave`, `Identificador`,
`Código`, `Req`) and a text column (`Descripción`, `Requerimiento`, `Requisito`, `Description`,
`Requirement`); optional `Título`/`Nombre`/`Title`, `Prioridad`/`Priority`, `Tipo`/`Type`,
`Componente`/`Módulo`/`Component`. Header matching ignores case and accents. Each row whose id
matches the spec-id grammar becomes a `requirement`; the nearest `##`/`###` heading above the
table becomes a `spec_component`.

`stories`: `HU-001` / `US-001` headings or list items with "Como <rol>, quiero <acción>, para
<beneficio>" / "As a <role>, I want …, so that …", and an acceptance-criteria list ("Criterios de
aceptación" / "Acceptance criteria"): numbered or bulleted items, or Dado/Cuando/Entonces (Given/
When/Then) lines. The story is a `requirement`; each criterion a child requirement `HU-001.1`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ad2v import ids, ir

FULL_ID_RE = re.compile(r"^" + ids.SPEC_ID_PATTERN + r"$")

ID_HEADERS = frozenset({"id", "clave", "identificador", "codigo", "req", "req id", "id req"})
TEXT_HEADERS = frozenset({"descripcion", "requerimiento", "requisito", "description", "requirement"})
TITLE_HEADERS = frozenset({"titulo", "nombre", "title", "name"})
PRIORITY_HEADERS = frozenset({"prioridad", "priority"})
TYPE_HEADERS = frozenset({"tipo", "type"})
COMPONENT_HEADERS = frozenset({"componente", "modulo", "component", "module"})
SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
HEADING_RE = re.compile(r"^(?P<h>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
NONFUNCTIONAL_TYPE_RE = re.compile(r"no[\s-]*funcional|non[\s-]*functional|\bnfr\b|\brnf\b|calidad|quality")


def norm(s: str) -> str:
    """Lower-case, accents and markup removed, spaces collapsed (header and actor matching)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[*_`]", "", s).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s-]", " ", s)).strip()


def split_row(line: str) -> list[str] | None:
    """Cells of a Markdown table row, or None. `\\|` and pipes inside `code` stay in the cell."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    cells: list[str] = []
    cur: list[str] = []
    code = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if c == "`":
            code = not code
        if c == "|" and not code:
            cells.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    cells.append("".join(cur))
    cells = cells[1:]  # before the leading pipe
    if cells and not cells[-1].strip():
        cells = cells[:-1]  # after the trailing pipe
    return [re.sub(r"\s*<br\s*/?>\s*", " ", c).strip() for c in cells]


def _clean_id(cell: str) -> str:
    return re.sub(r"[*`\[\]]", "", cell).strip()


def _columns(header: list[str]) -> dict[str, int] | None:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        n = norm(h)
        for key, names in (
            ("id", ID_HEADERS),
            ("text", TEXT_HEADERS),
            ("title", TITLE_HEADERS),
            ("priority", PRIORITY_HEADERS),
            ("type", TYPE_HEADERS),
            ("component", COMPONENT_HEADERS),
        ):
            if n in names and key not in cols:
                cols[key] = i
                break
    return cols if "id" in cols and "text" in cols else None


def tables(lines: list[str]) -> list[dict[str, Any]]:
    """Requirement tables: [{header_line, columns, rows: [(line_no, cells)], notes}] (1-based)."""
    out: list[dict[str, Any]] = []
    i = 0
    fence = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            fence = not fence
        header = None if fence else split_row(line)
        if header is not None and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]):
            cols = _columns(header)
            j = i + 2
            rows: list[tuple[int, list[str]]] = []
            notes: list[str] = []
            while j < len(lines):
                cells = split_row(lines[j])
                if cells is not None:
                    rows.append((j + 1, cells))
                elif lines[j].strip() and rows and not HEADING_RE.match(lines[j]):
                    # a row continued on the next line (not Markdown, but common): appended to the
                    # last cell, and reported
                    last_no, last = rows[-1]
                    cont = split_row("|" + lines[j].strip()) or [lines[j].strip()]
                    last[-1] = (last[-1] + " " + cont[0]).strip()
                    last.extend(cont[1:])
                    notes.append(f"line {j + 1}: continues the row of line {last_no}")
                else:
                    break
                j += 1
            if cols is not None:
                out.append({"header_line": i + 1, "columns": cols, "rows": rows, "notes": notes})
            i = j
            continue
        i += 1
    return out


def detect_table(text: str) -> bool:
    for t in tables(text.split("\n")):
        idc = t["columns"]["id"]
        if any(len(c) > idc and FULL_ID_RE.match(_clean_id(c[idc])) for _, c in t["rows"]):
            return True
    return False


# -- stories ------------------------------------------------------------------------------------
STORY_HEAD_RE = re.compile(
    r"^(?:#{1,6}\s+|\s*[-*]\s+|\s*\d+[.)]\s+)?(?:\*\*)?(?P<id>(?:HU|US)-[0-9]+)(?:\*\*)?"
    r"\s*(?:[:.\-–—]\s*(?P<rest>.*?))?\s*$"
)
STORY_ES_RE = re.compile(
    r"\bcomo\s+(?:(?:un|una|el|la|los|las)\s+)?(?P<actor>.+?),?\s+quiero\s+(?P<action>.+?)"
    r"(?:,?\s+(?:para(?:\s+que)?|de\s+modo\s+que|a\s+fin\s+de)\s+(?P<benefit>.+?))?\s*\.?\s*$",
    re.I,
)
STORY_EN_RE = re.compile(
    r"\bas\s+(?:(?:an?|the)\s+)?(?P<actor>.+?),?\s+I\s+want\s+(?:to\s+)?(?P<action>.+?)"
    r"(?:,?\s+so\s+that\s+(?P<benefit>.+?))?\s*\.?\s*$",
    re.I,
)
CRITERIA_RE = re.compile(
    r"^\s*(?:#{2,6}\s+)?(?:\*\*)?\s*(?:criterios\s+de\s+aceptaci[oó]n|acceptance\s+criteria)\s*:?\s*(?:\*\*)?:?\s*$",
    re.I,
)
ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(?P<text>.+?)\s*$")
GWT_WORDS = r"Dado|Dada|Dados|Dadas|Cuando|Entonces|Y|Pero|Given|When|Then|And|But"
GWT_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?(?P<kw>" + GWT_WORDS + r")(?:\*\*)?\s+(?P<rest>.+?)\s*$")
GIVEN = frozenset({"dado", "dada", "dados", "dadas", "given"})
WHEN = frozenset({"cuando", "when"})
THEN = frozenset({"entonces", "then"})
GWT_SPLIT_RE = re.compile(r"(?:\*\*)?\b(" + GWT_WORDS + r")\b(?:\*\*)?", re.I)


def detect_stories(text: str) -> bool:
    lines = text.split("\n")
    heads = [x for x in lines if STORY_HEAD_RE.match(x)]
    if not heads:
        return False
    return any(STORY_ES_RE.search(x) or STORY_EN_RE.search(x) or CRITERIA_RE.match(x) for x in lines)


def story_parts(text: str) -> dict[str, str]:
    t = re.sub(r"\*\*", "", text).strip()
    m = STORY_ES_RE.search(t) or STORY_EN_RE.search(t)
    if not m:
        return {}
    out = {k: v.strip() for k, v in m.groupdict().items() if v}
    if "actor" in out:
        out["actor"] = norm(out["actor"])
    return out


def gwt(text: str) -> dict[str, str]:
    """{given, when, then} from a Given/When/Then (Dado/Cuando/Entonces) text; And/Y extends."""
    parts = GWT_SPLIT_RE.split(re.sub(r"\*\*", "", text))
    out: dict[str, str] = {}
    cur: str | None = None
    for i in range(1, len(parts), 2):
        kw, body = parts[i].lower(), parts[i + 1].strip(" ,;")
        key = "given" if kw in GIVEN else "when" if kw in WHEN else "then" if kw in THEN else cur
        if key is None:
            continue
        out[key] = f"{out[key]} y {body}".strip() if key in out and key == cur else body
        cur = key
    return out if ("given" in out or "when" in out) and "then" in out else {}


def criteria(lines: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    """(first line, last line, text) per acceptance criterion."""
    out: list[tuple[int, int, str]] = []
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if block:
            out.append((block[0][0], block[-1][0], " ".join(t for _, t in block)))
            block.clear()

    for no, line in lines:
        if not line.strip():
            continue
        g = GWT_LINE_RE.match(line)
        if g:
            kw = g.group("kw").lower()
            if kw in GIVEN and any(
                GWT_LINE_RE.match(t) and GWT_LINE_RE.match(t).group("kw").lower() in THEN for _, t in block
            ):
                flush()
            block.append((no, f"{g.group('kw')} {g.group('rest')}"))
            continue
        flush()
        m = ITEM_RE.match(line)
        if m:
            out.append((no, no, m.group("text")))
        elif out:  # an item continued on the next line
            a, _, t = out[-1]
            out[-1] = (a, no, f"{t} {line.strip()}")
    flush()
    return out


# -- extraction ---------------------------------------------------------------------------------
def _doc(graph: ir.Graph, rel: str, text: str, preset: str) -> ir.Node:
    lines = text.split("\n")
    return graph.add_node(
        ir.Node(
            "spec",
            "spec_doc",
            rel.rsplit("/", 1)[-1],
            rel,
            path=rel,
            span_start_line=1,
            span_end_line=max(1, len(lines) - (1 if text.endswith("\n") else 0)),
            content_hash=ids.content_hash(text),
            attrs={"format": "markdown", "preset": preset},
        )
    )


def _req(graph, rel, rid, parent, a, b, block, attrs) -> ir.Node:  # noqa: ANN001
    return graph.add_node(
        ir.Node(
            "spec",
            "requirement",
            rid,
            rid,
            parent_id=parent.id,
            path=rel,
            span_start_line=a,
            span_end_line=b,
            content_hash=ids.content_hash(block),
            attrs=attrs,
        )
    )


def extract_table(graph: ir.Graph, rel: str, text: str, parse_ears) -> None:  # noqa: ANN001
    doc = _doc(graph, rel, text, "table")
    lines = text.split("\n")
    found = tables(lines)
    in_table = {no for t in found for no in range(t["header_line"], t["header_line"] + 2)}
    in_table |= {no for t in found for no, _ in t["rows"]}
    headings = [
        (i, m.group("text"), len(m.group("h"))) for i, x in enumerate(lines, 1) if (m := HEADING_RE.match(x))
    ]
    comps: dict[int, ir.Node] = {}
    skipped: list[str] = []
    dupes: list[str] = []
    notes: list[str] = []
    for t in found:
        above = [h for h in headings if h[0] < t["header_line"] and h[2] >= 2]
        parent = doc
        if above:
            hl, htext, _ = above[-1]
            if hl not in comps:
                comps[hl] = graph.add_node(
                    ir.Node(
                        "spec",
                        "spec_component",
                        htext,
                        f"{rel}::{htext}",
                        parent_id=doc.id,
                        path=rel,
                        span_start_line=hl,
                        span_end_line=hl,
                        content_hash=ids.content_hash(lines[hl - 1]),
                        attrs={"preset": "table", "spec_id": None},
                    )
                )
            parent = comps[hl]
        cols = t["columns"]
        notes += t["notes"]
        for no, cells in t["rows"]:
            if len(cells) <= max(cols.values()):
                cells = cells + [""] * (max(cols.values()) + 1 - len(cells))
            rid = _clean_id(cells[cols["id"]])
            if not FULL_ID_RE.match(rid):
                if rid:
                    skipped.append(rid)
                continue
            body = cells[cols["text"]].strip()
            attrs: dict[str, Any] = {"text": body, "spec_id": rid, **parse_ears(body)}
            for key in ("title", "priority", "component"):
                if key in cols and cells[cols[key]].strip():
                    attrs[key] = re.sub(r"\*\*", "", cells[cols[key]]).strip()
            if "type" in cols and cells[cols["type"]].strip():
                attrs["type"] = cells[cols["type"]].strip()
                if NONFUNCTIONAL_TYPE_RE.search(norm(attrs["type"])):
                    attrs["requirement_type"] = "nonfunctional"
            key = ids.node_id("spec", "requirement", rid)
            if key in graph.nodes:
                dupes.append(rid)
                continue
            # a `Componente` cell groups the row under a spec component of that name, below the
            # heading's (it can then pair with a container of the same name, ADR-0069)
            owner = parent
            if attrs.get("component"):
                cname = attrs["component"]
                cq = f"{rel}::{cname}" if parent is doc else f"{parent.qualified_name}::{cname}"
                owner = graph.nodes.get(ids.node_id("spec", "spec_component", cq)) or graph.add_node(
                    ir.Node(
                        "spec",
                        "spec_component",
                        cname,
                        cq,
                        parent_id=parent.id,
                        path=rel,
                        span_start_line=no,
                        span_end_line=no,
                        content_hash=ids.attrs_hash("spec_component", cname, {}),
                        attrs={"preset": "table", "spec_id": None, "from_column": True},
                    )
                )
            _req(graph, rel, rid, owner, no, no, lines[no - 1], attrs)
            for p_ in (parent, owner):
                if p_ is not doc:
                    p_.span_end_line = max(p_.span_end_line or no, no)
    doc.attrs["prose"] = "\n".join(x for i, x in enumerate(lines, 1) if i not in in_table).strip()
    if skipped:
        doc.attrs["skipped_ids"] = sorted(set(skipped))
    if dupes:
        doc.attrs["duplicate_ids"] = sorted(set(dupes))
    if notes:
        doc.attrs["table_notes"] = notes


def extract_stories(graph: ir.Graph, rel: str, text: str, parse_ears) -> None:  # noqa: ANN001
    doc = _doc(graph, rel, text, "stories")
    lines = text.split("\n")
    starts = [i for i, x in enumerate(lines, 1) if STORY_HEAD_RE.match(x)]
    used: set[int] = set()
    for k, start in enumerate(starts):
        nxt = starts[k + 1] if k + 1 < len(starts) else len(lines) + 1
        head = STORY_HEAD_RE.match(lines[start - 1])
        assert head is not None
        sid = head.group("id")
        rest = (head.group("rest") or "").strip()
        # the story's own lines end at the criteria heading, at a heading of the same or a higher
        # level, or at the next story
        level = len(m.group("h")) if (m := HEADING_RE.match(lines[start - 1])) else 7
        end = nxt - 1
        crit_at: int | None = None
        for i in range(start + 1, nxt):
            x = lines[i - 1]
            if CRITERIA_RE.match(x):
                crit_at = i
                break
            hm = HEADING_RE.match(x)
            if hm and len(hm.group("h")) <= level:
                end = i - 1
                break
        story_end = (crit_at - 1) if crit_at else end
        while story_end > start and not lines[story_end - 1].strip():
            story_end -= 1
        body_lines = [lines[i - 1].strip() for i in range(start + 1, story_end + 1) if lines[i - 1].strip()]
        sentence = " ".join([rest, *body_lines]).strip() if not story_parts(rest) else rest
        parts = story_parts(sentence) or story_parts(" ".join(body_lines))
        title = rest if rest and not story_parts(rest) else None
        attrs: dict[str, Any] = {"text": re.sub(r"\*\*", "", sentence).strip(), "spec_id": sid, "story": True}
        attrs.update(parts)
        if title:
            attrs["title"] = re.sub(r"\*\*", "", title).strip()
        story = _req(graph, rel, sid, doc, start, story_end, "\n".join(lines[start - 1 : story_end]), attrs)
        used.update(range(start, story_end + 1))
        if crit_at is None:
            continue
        stop = crit_at
        for i in range(crit_at + 1, nxt):
            hm = HEADING_RE.match(lines[i - 1])
            if hm and len(hm.group("h")) <= level:
                break
            stop = i
        items = criteria([(i, lines[i - 1]) for i in range(crit_at + 1, stop + 1)])
        used.update(range(crit_at, stop + 1))
        for n, (a, b, ctext) in enumerate(items, start=1):
            cid = f"{sid}.{n}"
            cattrs: dict[str, Any] = {
                "text": re.sub(r"\*\*", "", ctext).strip(),
                "spec_id": cid,
                "criterion": True,
            }
            g = gwt(ctext)
            if g:
                cattrs["gwt"] = g
                cattrs["ears"] = None
            else:
                cattrs.update(parse_ears(cattrs["text"]))
            _req(graph, rel, cid, story, a, b, "\n".join(lines[a - 1 : b]), cattrs)
    doc.attrs["prose"] = "\n".join(x for i, x in enumerate(lines, 1) if i not in used).strip()
