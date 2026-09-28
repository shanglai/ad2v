"""JUnit XML test-result ingestion (format spec §6.5). Standard library only.

Matching rules for pytest's JUnit output (`pytest --junitxml`):

1. `name` loses any parametrization suffix: `test_x[a-1]` -> `test_x`.
2. `classname` is the dotted module path relative to pytest's rootdir, optionally followed by
   class names: `api.tests.test_matching` or `tests.test_api.TestRoutes`.
3. For i = len(parts) .. 1: the module is `parts[:i]` joined with `/` + `.py`, and the classes
   are `parts[i:]`. The module matches every extracted module whose path equals it or ends with
   `/` + it (the rootdir may differ from the repo root). The test qualified name is
   `<module path>::<Class...>.<name>`. The first i that yields function nodes wins.
4. If the testcase has a `file` attribute, candidates whose module path ends with it win.
5. Exactly one candidate: matched. Zero: unmatched (`not_found`). Several: unmatched
   (`ambiguous`). Unmatched cases are reported, never an error.

Outcome: `<failure>` or `<error>` child -> failed; `<skipped>` -> skipped; otherwise passed.
If several results map to one test, the worst wins (failed > skipped > passed).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ad2v import ids, ir

PARAM_RE = re.compile(r"\[.*\]$")
OUTCOME_ORDER = {"passed": 0, "skipped": 1, "failed": 2}


class JUnitError(ValueError):
    pass


@dataclass
class Ingested:
    results: dict[str, ir.TestResult] = field(default_factory=dict)  # test node id -> result
    unmatched: list[dict[str, str]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # source_file -> content_hash
    cases: int = 0

    @property
    def files_hash(self) -> str:
        return ids.tree_hash(self.files)


def _outcome(case: ET.Element) -> str:
    if case.find("failure") is not None or case.find("error") is not None:
        return "failed"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def _source_name(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.name


def match_case(classname: str, name: str, file_attr: str | None, graph: ir.Graph) -> tuple[str | None, str]:
    """Return (test node id, reason) using the documented rules."""
    name = PARAM_RE.sub("", name)
    modules = sorted(n.path for n in graph.nodes.values() if n.kind == "module" and n.path)
    parts = [p for p in classname.split(".") if p]
    for i in range(len(parts), 0, -1):
        mod_rel = "/".join(parts[:i]) + ".py"
        classes = parts[i:]
        hits = []
        for m in modules:
            if m == mod_rel or m.endswith("/" + mod_rel):
                qn = f"{m}::{'.'.join([*classes, name])}"
                nid = ids.node_id("code", "function", qn)
                if nid in graph.nodes:
                    hits.append((m, nid))
        if file_attr and len(hits) > 1:
            f = file_attr.replace("\\", "/").lstrip("./")
            narrowed = [h for h in hits if h[0] == f or h[0].endswith("/" + f)]
            hits = narrowed or hits
        if len(hits) == 1:
            return hits[0][1], "matched"
        if len(hits) > 1:
            return None, "ambiguous"
    return None, "not_found"


def ingest(paths: list[Path], repo: Path, graph: ir.Graph) -> Ingested:
    out = Ingested()
    for path in sorted(paths, key=lambda p: _source_name(Path(p), repo)):
        path = Path(path)
        if not path.is_file():
            raise JUnitError(f"test results file not found: {path}")
        text = ids.read_normalized(path)
        source = _source_name(path, repo)
        out.files[source] = ids.content_hash(text)
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise JUnitError(f"invalid JUnit XML in {path}: {e}") from e
        for case in root.iter("testcase"):
            out.cases += 1
            classname = case.get("classname", "")
            name = case.get("name", "")
            nid, reason = match_case(classname, name, case.get("file"), graph)
            if nid is None:
                out.unmatched.append(
                    {"classname": classname, "name": name, "reason": reason, "source": source}
                )
                continue
            try:
                ms = round(float(case.get("time", "0") or 0) * 1000)
            except ValueError:
                ms = 0
            res = ir.TestResult(nid, _outcome(case), source, int(ms))
            prev = out.results.get(nid)
            if prev is None or OUTCOME_ORDER[res.outcome] > OUTCOME_ORDER[prev.outcome]:
                out.results[nid] = res
    out.unmatched.sort(key=lambda u: (u["source"], u["classname"], u["name"]))
    return out
