"""Short titles and requirement types for spec items (P9, ADR-0069). Deterministic.

Title: an explicit one wins (a table's `Título` column, a story or Kiro heading, the convention's
`- [REQ-001] (Título corto) …`). Otherwise it is derived: the EARS response (or the story's action,
or the raw text) without the system phrase ("el sistema deberá", "the system shall", "System
MUST"), its first `WORDS` words, cut at a word boundary, first letter upper-case.

Type: `attrs.requirement_type = "nonfunctional"` for ids whose prefix is in
`spec_ids.nonfunctional_prefixes` (default RNF, NFR, NF), or a table `Tipo`/`Type` cell that says
so. Non-functional requirements stay `specified` unless something links them; they are counted
apart (status summary, MCP overview, dogfood counts) and badged "NFR" in the viewer.
"""

from __future__ import annotations

import re

from ad2v import ir

WORDS = 6
DEFAULT_NONFUNCTIONAL_PREFIXES = ("RNF", "NFR", "NF")
SYSTEM_PHRASE_RE = re.compile(
    r"^(?:(?:el|la|los|las|the|a|an)\s+)?(?:[\w-]+\s+){0,3}?"
    r"(?:deber[aá]n?|debe(?:n)?|tendr[aá]n?\s+que|podr[aá]n?|shall|must|should|will|can)\s+",
    re.I,
)


# a title does not end on a function word ("… with a", "… de la")
TRAILING = frozenset(
    [
        "a",
        "an",
        "the",
        "to",
        "of",
        "in",
        "at",
        "on",
        "by",
        "for",
        "with",
        "from",
        "and",
        "or",
        "as",
        "that",
        "its",
        "their",
        "this",
        "sin",
        "entre",
        "menos",
        "más",
        "mas",
        "less",
        "more",
        "than",
        "que",
        "can",
        "may",
        "will",
        "must",
        "should",
        "puede",
        "pueden",
        "sobre",
        "hasta",
        "desde",
        "without",
        "into",
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "en",
        "con",
        "por",
        "para",
        "y",
        "o",
        "u",
        "un",
        "una",
        "unos",
        "unas",
        "que",
        "al",
        "su",
        "sus",
    ]
)


def short(text: str, words: int = WORDS) -> str:
    t = re.sub(r"[*_`]", "", text).strip()
    t = re.split(r"\s*\[", t, maxsplit=1)[0]  # "[NEEDS CLARIFICATION: …]" and similar markers
    t = SYSTEM_PHRASE_RE.sub("", t, count=1)
    ws = t.split()[:words]
    while len(ws) > 1 and ws[-1].lower().strip(".,;:") in TRAILING:
        ws.pop()
    if not ws:
        return ""
    out = " ".join(ws).rstrip(".,;:")
    return out[:1].upper() + out[1:]


def title_for(node: ir.Node) -> str:
    a = node.attrs
    explicit = a.get("title")
    if isinstance(explicit, str) and explicit.strip():
        return " ".join(explicit.split())
    g = a.get("gwt")
    if isinstance(g, dict) and isinstance(g.get("then"), str) and short(g["then"]):
        return short(g["then"])  # a Given/When/Then criterion: what must happen
    if not a.get("action") and isinstance(a.get("text"), str):
        from ad2v.extract.spec.team import story_parts

        story = story_parts(a["text"])  # a user story: its action is the title
        if story.get("action"):
            return short(story["action"]) or node.name
    for key in ("response", "action", "text"):
        v = a.get(key)
        if isinstance(v, str) and v.strip():
            got = short(v)
            if got:
                return got
    return node.name


def apply_titles(graph: ir.Graph) -> None:
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        if n.side == "spec" and n.kind == "requirement":
            n.attrs["title"] = title_for(n)


def prefix(spec_id: str) -> str:
    bare = spec_id.split(":", 1)[-1]
    return bare.split("-", 1)[0].upper()


def apply_types(graph: ir.Graph, prefixes: tuple[str, ...]) -> int:
    """Mark non-functional requirements; returns how many there are."""
    wanted = {p.upper() for p in prefixes}
    count = 0
    for nid in sorted(graph.nodes):
        n = graph.nodes[nid]
        if n.side != "spec" or n.kind != "requirement":
            continue
        if n.attrs.get("requirement_type") != "nonfunctional" and prefix(n.qualified_name) in wanted:
            n.attrs["requirement_type"] = "nonfunctional"
        if n.attrs.get("requirement_type") == "nonfunctional":
            count += 1
    return count
