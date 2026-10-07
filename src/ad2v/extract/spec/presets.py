"""SDD Markdown presets (P6.1, ADR-0048): deterministic parsers for common spec formats. No LLM.

- `ad2v`: the ad2v convention (docs/spec/spec-markdown-convention.md), parsed by `markdown.py`.
- `spec-kit` (github/spec-kit, templates pinned in ADR-0048): `specs/<NNN-feature>/spec.md`.
  The feature becomes a `spec_component` whose qualified name is the feature slug; each
  `**FR-001**:` / `**SC-001**:` line becomes a `requirement` with the namespaced id
  `<feature-slug>:FR-001`; each acceptance scenario (`1. **Given** …, **When** …, **Then** …`)
  becomes a `scenario` with `scenario_step`s, under its user story.
- `kiro` (kiro.dev): `.kiro/specs/<feature>/requirements.md`. The feature becomes a
  `spec_component`; `### Requirement N[: Title]` becomes requirement `<PREFIX>-N` (user story in
  attrs), and each numbered acceptance criterion becomes requirement `<PREFIX>-N.M`, a child,
  with Kiro-style EARS parsing (upper-case WHEN / IF / WHILE / WHERE / THE … SHALL).
- `custom`: regexes from ad2v.yaml (`spec_markdown:` rules).

Selection: the first `spec_markdown:` rule whose glob matches the repo-relative path wins;
otherwise by path and shape (Kiro path, spec-kit shape, ad2v markers); otherwise prose only.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

from ad2v import ids, ir
from ad2v.extract.spec import markdown, team

PRESETS = ("ad2v", "spec-kit", "kiro", "custom", "table", "stories")
FULL_ID_RE = re.compile(r"^" + ids.SPEC_ID_PATTERN + r"$")


class PresetError(ValueError):
    pass


@dataclass(frozen=True)
class Choice:
    preset: str
    namespace: str | None = None  # spec-kit: the feature slug (id namespace)
    prefix: str | None = None  # kiro: the synthesized id prefix
    feature: str | None = None  # the feature folder name
    rule: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)  # custom: regexes


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "spec"


def kiro_prefix(feature: str) -> str:
    """Upper-case alphanumeric slug of the feature folder, at most 12 chars, starting with a letter."""
    s = re.sub(r"[^A-Za-z0-9]", "", feature).upper()
    if not s or not s[0].isalpha():
        s = "K" + s
    return s[:12]


# -- selection -------------------------------------------------------------------------------------
SPECKIT_ID_RE = re.compile(r"^\s*[-*]\s+\*\*(?P<id>(?:FR|SC)-[0-9]+)\*\*\s*:?\s*(?P<text>.+?)\s*$")
SPECKIT_FR_HEADING_RE = re.compile(r"^#{2,4}\s+Functional Requirements\b", re.I)


def _feature(path: str) -> str:
    parts = path.split("/")
    return parts[-2] if len(parts) >= 2 else parts[-1].rsplit(".", 1)[0]


def detect(path: str, text: str) -> str | None:
    """The preset recognizing this file by path and shape, or None (prose only)."""
    name = path.rsplit("/", 1)[-1]
    if "/.kiro/specs/" in "/" + path and name == "requirements.md":
        return "kiro"
    lines = text.split("\n")
    if (
        name == "spec.md"
        and any(SPECKIT_FR_HEADING_RE.match(x) for x in lines)
        and any(SPECKIT_ID_RE.match(x) for x in lines)
    ):
        return "spec-kit"
    found = markdown.detect(path, text)
    if found:
        return found
    # P9 (ADR-0069): team formats, after every earlier preset so their files keep their reader
    if team.detect_table(text):
        return "table"
    if team.detect_stories(text):
        return "stories"
    return None


def choose(path: str, text: str, rules: list[dict[str, Any]]) -> Choice | None:
    """`path` is repo-relative (POSIX). Manifest rules first, then auto-selection."""
    preset: str | None = None
    rule: dict[str, Any] = {}
    for r in rules:
        if fnmatch.fnmatchcase(path, str(r.get("glob", ""))):
            preset, rule = str(r.get("preset")), r
            break
    if preset is None:
        preset = detect(path, text)
    if preset is None:
        return None
    if preset not in PRESETS:
        raise PresetError(f"spec_markdown: unknown preset {preset!r} (one of {', '.join(PRESETS)})")
    feature = _feature(path)
    if preset == "spec-kit":
        return Choice(
            preset, namespace=slug(str(rule.get("namespace") or feature)), feature=feature, rule=rule
        )
    if preset == "kiro":
        return Choice(
            preset, prefix=str(rule.get("id_prefix") or kiro_prefix(feature)), feature=feature, rule=rule
        )
    if preset == "custom":
        for k in ("requirement",):
            if not rule.get(k):
                raise PresetError(f"spec_markdown rule for {rule.get('glob')!r}: custom needs `{k}`")
        return Choice(preset, feature=feature, rule=rule)
    return Choice(preset, feature=feature)


def assign_prefixes(choices: dict[str, Choice]) -> dict[str, Choice]:
    """Kiro prefixes must be unique: collisions get a deterministic numeric suffix (path order)."""
    out = dict(choices)
    seen: dict[str, int] = {}
    for path in sorted(choices):
        ch = choices[path]
        if ch.preset != "kiro" or ch.prefix is None:
            continue
        n = seen.get(ch.prefix, 0) + 1
        seen[ch.prefix] = n
        if n > 1:
            out[path] = Choice(ch.preset, ch.namespace, f"{ch.prefix}{n}", ch.feature, ch.rule)
    return out


# -- shared pieces ------------------------------------------------------------------------------------
def _doc(graph: ir.Graph, rel: str, text: str, preset: str) -> tuple[ir.Node, list[str]]:
    lines = text.split("\n")
    doc = graph.add_node(
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
    return doc, lines


def _visible(lines: list[str]) -> list[bool]:
    """False for lines inside fenced code or HTML comments (template guidance)."""
    out, fence, comment = [], False, False
    for line in lines:
        s = line.strip()
        if not comment and s.startswith("```"):
            fence = not fence
            out.append(False)
            continue
        if not fence and not comment and s.startswith("<!--"):
            comment = "-->" not in s
            out.append(False)
            continue
        if comment:
            if "-->" in s:
                comment = False
            out.append(False)
            continue
        out.append(not fence)
    return out


def _span(lines: list[str], a: int, b: int) -> str:
    return "\n".join(lines[a - 1 : b])


def _end(lines: list[str], start: int, stops: list[int]) -> int:
    later = [s for s in stops if s > start]
    end = (later[0] - 1) if later else len(lines)
    while end > start and not lines[end - 1].strip():
        end -= 1
    return end


KIRO_EARS: list[tuple[str, re.Pattern[str]]] = [
    (
        "unwanted",
        re.compile(
            r"^IF\s+(?P<trigger>.+?),?\s+THEN\s+(?:THE\s+)?(?P<system>.+?)\s+SHALL\s+(?P<response>.+?)\.?$"
        ),
    ),
    (
        "event",
        re.compile(
            r"^(?:WHILE\s+(?P<precondition>.+?),?\s+)?WHEN\s+(?P<trigger>.+?),?\s+(?:THEN\s+(?:THE\s+)?|THE\s+)"
            r"(?P<system>.+?)\s+SHALL\s+(?P<response>.+?)\.?$"
        ),
    ),
    (
        "state",
        re.compile(
            r"^WHILE\s+(?P<precondition>.+?),?\s+(?:THE\s+)?(?P<system>.+?)\s+SHALL\s+(?P<response>.+?)\.?$"
        ),
    ),
    (
        "optional",
        re.compile(
            r"^WHERE\s+(?P<precondition>.+?),?\s+(?:THE\s+)?(?P<system>.+?)\s+SHALL\s+(?P<response>.+?)\.?$"
        ),
    ),
    ("ubiquitous", re.compile(r"^(?:THE|ALL)\s+(?P<system>.+?)\s+SHALL\s+(?P<response>.+?)\.?$")),
]


def parse_ears(text: str) -> dict[str, Any]:
    """Kiro's upper-case EARS first, then the ad2v (sentence-case) EARS templates."""
    t = text.strip()
    for name, pat in KIRO_EARS:
        m = pat.match(t)
        if m:
            return {"ears": name, **{k: v for k, v in m.groupdict().items() if v is not None}}
    return markdown.parse_ears(t)


def _requirement(graph, rel, qname, name, parent, line_no, line, attrs) -> ir.Node:  # noqa: ANN001
    return graph.add_node(
        ir.Node(
            "spec",
            "requirement",
            name,
            qname,
            parent_id=parent.id,
            path=rel,
            span_start_line=line_no,
            span_end_line=line_no,
            content_hash=ids.content_hash(line),
            attrs=attrs,
        )
    )


# -- spec-kit -------------------------------------------------------------------------------------------
STORY_RE = re.compile(
    r"^###\s+User Story\s+(?P<n>\d+)\s*[-–—:]\s*(?P<title>.+?)(?:\s*\(Priority:\s*(?P<prio>[^)]+)\))?\s*$",
    re.I,
)
SCENARIO_RE = re.compile(r"^\s*(?P<n>\d+)\.\s+(?P<body>.*\*\*Given\*\*.*)$")
STEP_SPLIT_RE = re.compile(r"\*\*(Given|When|Then|And|But)\*\*")
TITLE_RE = re.compile(r"^#\s+(?:Feature Specification:\s*)?(?P<title>.+?)\s*$")
CLARIFY_RE = re.compile(r"\[NEEDS CLARIFICATION:", re.I)


def extract_speckit(graph: ir.Graph, rel: str, text: str, ch: Choice) -> None:
    doc, lines = _doc(graph, rel, text, "spec-kit")
    vis = _visible(lines)
    title = next(
        (m.group("title") for i, x in enumerate(lines) if vis[i] and (m := TITLE_RE.match(x))), ch.feature
    )
    ns = ch.namespace or "spec"
    comp = graph.add_node(
        ir.Node(
            "spec",
            "spec_component",
            title or ns,
            ns,
            parent_id=doc.id,
            path=rel,
            span_start_line=1,
            span_end_line=doc.span_end_line,
            content_hash=ids.content_hash(text),
            attrs={"preset": "spec-kit", "feature": ch.feature, "namespace": ns, "spec_id": None},
        )
    )
    story: dict[str, Any] | None = None
    prose: list[str] = []
    seen_q: dict[str, int] = {}
    for i, line in enumerate(lines, start=1):
        if not vis[i - 1]:
            continue
        sm = STORY_RE.match(line)
        if sm:
            story = {
                "n": int(sm.group("n")),
                "title": sm.group("title").strip(),
                "priority": sm.group("prio"),
            }
            continue
        if line.startswith("## "):
            story = None
        rm = SPECKIT_ID_RE.match(line)
        if rm:
            local, body = rm.group("id"), rm.group("text")
            attrs = {
                "text": body,
                "spec_id": f"{ns}:{local}",
                "local_id": local,
                "category": "functional" if local.startswith("FR-") else "success_criterion",
                **parse_ears(body),
            }
            if CLARIFY_RE.search(body):
                attrs["needs_clarification"] = True
            _requirement(graph, rel, f"{ns}:{local}", local, comp, i, line, attrs)
            continue
        scm = SCENARIO_RE.match(line)
        if scm and story is not None:
            label = f"User Story {story['n']}::Scenario {scm.group('n')}"
            n = seen_q.get(label, 0) + 1
            seen_q[label] = n
            qn = f"{rel}::{label}" + (f"#{n}" if n > 1 else "")
            snode = graph.add_node(
                ir.Node(
                    "spec",
                    "scenario",
                    f"{story['title']}: scenario {scm.group('n')}",
                    qn,
                    parent_id=comp.id,
                    path=rel,
                    span_start_line=i,
                    span_end_line=i,
                    content_hash=ids.content_hash(line),
                    attrs={
                        "keyword": "Scenario",
                        "user_story": story["title"],
                        "priority": story["priority"],
                        "preset": "spec-kit",
                    },
                )
            )
            parts = STEP_SPLIT_RE.split(scm.group("body"))
            for k, j in enumerate(range(1, len(parts) - 1, 2), start=1):
                kw, step_text = parts[j], parts[j + 1].strip().strip(",").strip()
                graph.add_node(
                    ir.Node(
                        "spec",
                        "scenario_step",
                        f"{kw} {step_text}",
                        f"{qn}::step[{k}]",
                        parent_id=snode.id,
                        path=rel,
                        span_start_line=i,
                        span_end_line=i,
                        content_hash=ids.content_hash(f"{kw} {step_text}"),
                        attrs={"keyword": kw, "keyword_type": None, "text": step_text},
                    )
                )
            continue
        prose.append(line)
    doc.attrs["prose"] = "\n".join(prose).strip()


# -- Kiro ----------------------------------------------------------------------------------------------
KIRO_REQ_RE = re.compile(r"^###\s+Requirement\s+(?P<n>\d+)(?:\s*[:.\-–—]\s*(?P<title>.+?))?\s*$", re.I)
KIRO_STORY_RE = re.compile(r"^\*\*User Story:?\*\*:?\s*(?P<text>.+?)\s*$", re.I)
KIRO_AC_RE = re.compile(r"^#{3,5}\s+Acceptance Criteria\b", re.I)
KIRO_CRIT_RE = re.compile(r"^\s*(?P<m>\d+)\.\s+(?P<text>.+?)\s*$")


def extract_kiro(graph: ir.Graph, rel: str, text: str, ch: Choice) -> None:
    doc, lines = _doc(graph, rel, text, "kiro")
    vis = _visible(lines)
    prefix = ch.prefix or kiro_prefix(ch.feature or "spec")
    comp = graph.add_node(
        ir.Node(
            "spec",
            "spec_component",
            ch.feature or prefix,
            prefix,
            parent_id=doc.id,
            path=rel,
            span_start_line=1,
            span_end_line=doc.span_end_line,
            content_hash=ids.content_hash(text),
            attrs={"preset": "kiro", "feature": ch.feature, "id_prefix": prefix, "spec_id": None},
        )
    )
    req: ir.Node | None = None
    in_ac = False
    intro: list[str] = []
    for i, line in enumerate(lines, start=1):
        if not vis[i - 1]:
            continue
        rm = KIRO_REQ_RE.match(line)
        if rm:
            n = int(rm.group("n"))
            title = (rm.group("title") or "").strip()
            req = _requirement(
                graph,
                rel,
                f"{prefix}-{n}",
                f"{prefix}-{n}",
                comp,
                i,
                line,
                {"text": title, "title": title or None, "spec_id": f"{prefix}-{n}", "ears": None},
            )
            in_ac = False
            continue
        if req is None:
            if line.startswith("## Requirements"):
                continue
            intro.append(line)
            continue
        if line.startswith("#") and not KIRO_AC_RE.match(line) and not line.startswith("###"):
            req, in_ac = None, False  # a new level-2 section ends the requirements
            intro.append(line)
            continue
        sm = KIRO_STORY_RE.match(line)
        if sm:
            req.attrs["user_story"] = sm.group("text")
            if not req.attrs.get("text"):
                req.attrs["text"] = sm.group("text")
            continue
        if KIRO_AC_RE.match(line):
            in_ac = True
            continue
        cm = KIRO_CRIT_RE.match(line) if in_ac else None
        if cm:
            m = int(cm.group("m"))
            body = cm.group("text")
            _requirement(
                graph,
                rel,
                f"{req.qualified_name}.{m}",
                f"{req.qualified_name}.{m}",
                req,
                i,
                line,
                {"text": body, "spec_id": f"{req.qualified_name}.{m}", "criterion": True, **parse_ears(body)},
            )
            req.span_end_line = i
            continue
    comp.attrs["text"] = "\n".join(intro).strip()
    doc.attrs["prose"] = comp.attrs["text"]


# -- custom ------------------------------------------------------------------------------------------
def extract_custom(graph: ir.Graph, rel: str, text: str, ch: Choice) -> None:
    doc, lines = _doc(graph, rel, text, "custom")
    vis = _visible(lines)
    rule = ch.rule
    try:
        comp_re = re.compile(rule["component"]) if rule.get("component") else None
        req_re = re.compile(rule["requirement"])
    except re.error as e:
        raise PresetError(f"spec_markdown custom regex for {rule.get('glob')!r}: {e}") from e
    ears = bool(rule.get("ears", True))
    comp: ir.Node | None = None
    prose: list[str] = []
    skipped: list[str] = []
    for i, line in enumerate(lines, start=1):
        if not vis[i - 1]:
            continue
        cm = comp_re.match(line) if comp_re is not None else None
        if cm:
            gd = cm.groupdict()
            name = (gd.get("name") or line).strip()
            cid = gd.get("id")
            comp = graph.add_node(
                ir.Node(
                    "spec",
                    "spec_component",
                    name,
                    cid if cid and FULL_ID_RE.match(cid) else f"{rel}::{name}",
                    parent_id=doc.id,
                    path=rel,
                    span_start_line=i,
                    span_end_line=i,
                    attrs={"preset": "custom", "spec_id": cid},
                )
            )
            continue
        rm = req_re.match(line)
        if rm:
            rid, body = rm.group("id"), (rm.groupdict().get("text") or "").strip()
            if not FULL_ID_RE.match(rid):
                skipped.append(rid)
                continue
            attrs = {"text": body, "spec_id": rid, **(parse_ears(body) if ears else {"ears": None})}
            _requirement(graph, rel, rid, rid, comp if comp is not None else doc, i, line, attrs)
            if comp is not None:
                comp.span_end_line = i
            continue
        prose.append(line)
    doc.attrs["prose"] = "\n".join(prose).strip()
    if skipped:
        doc.attrs["skipped_ids"] = sorted(set(skipped))


def extract(graph: ir.Graph, rel: str, text: str, ch: Choice | None) -> None:
    if ch is None or ch.preset == "ad2v":
        markdown.extract(graph, rel, text)
        if ch is not None:
            graph.nodes[ids.node_id("spec", "spec_doc", rel)].attrs["preset"] = "ad2v"
    elif ch.preset == "spec-kit":
        extract_speckit(graph, rel, text, ch)
    elif ch.preset == "kiro":
        extract_kiro(graph, rel, text, ch)
    elif ch.preset == "table":
        team.extract_table(graph, rel, text, parse_ears)
    elif ch.preset == "stories":
        team.extract_stories(graph, rel, text, parse_ears)
    else:
        extract_custom(graph, rel, text, ch)
