"""Zero-config checks (P10 M1, ADR-0073): what a map built without `ad2v.yaml` may get wrong.

P9 showed that a zero-config `extract` on an existing repository can mislead: an unresolved
settings prefix makes endpoints look `missing` and routes look orphaned, and one fallback
container hides the services. When `extract` runs without a manifest it now names each such
condition and recommends `ad2v init`. The list is stored in `meta.unconfigured_warnings` (file
level, informative); the viewer and the MCP overview show it as a banner.

Also here: the test-name prefixes derived from the spec ids found in this epoch's specs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ad2v import ir
from ad2v.extract import files as filewalk

CONTAINER_FILES = (
    "pyproject.toml",
    "setup.py",
    "package.json",
    "Dockerfile",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)
IAC_NAMES = ("Pulumi.yaml", "Pulumi.yml", "Chart.yaml", ".terraform.lock.hcl")
SPEC_ID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-[0-9]+(?:\.[0-9]+)*$")


def spec_id_prefixes(graph: ir.Graph) -> list[str]:
    """Upper-case prefixes of the requirement and spec-component ids in `graph` (sorted)."""
    out = set()
    for n in graph.nodes.values():
        if n.side != "spec" or n.kind not in ("requirement", "spec_component"):
            continue
        m = SPEC_ID_RE.match(n.qualified_name.split(":", 1)[-1])
        if m:
            out.add(m.group(1).upper())
    return sorted(out)


def derived_test_prefixes(found: list[str], configured: tuple[str, ...]) -> list[str]:
    """Prefixes found in the specs that the configuration does not list yet (sorted)."""
    have = {p.upper() for p in configured}
    return [p for p in found if p not in have]


def _markers(repo: Path, exclude: tuple[str, ...], spec_labels: tuple[str, ...]) -> list[str]:
    """Folders below the root (depth <= 3) holding a project manifest, outermost only."""
    names = set(CONTAINER_FILES)
    hits = filewalk.walk(repo, exclude, include=lambda p: p.rsplit("/", 1)[-1] in names)
    dirs = set()
    for f in hits:
        d = f.rsplit("/", 1)[0] if "/" in f else "."
        if d == "." or d.count("/") > 2:
            continue
        if any(d == s or d.startswith(s + "/") for s in spec_labels):
            continue
        dirs.add(d)
    return sorted(d for d in dirs if not any(o != d and d.startswith(o + "/") for o in dirs))


def iac_dirs(repo: Path, exclude: tuple[str, ...]) -> list[str]:
    """Folders with Terraform or other infrastructure-as-code markers (sorted)."""
    hits = filewalk.walk(
        repo, exclude, include=lambda p: p.endswith(".tf") or p.rsplit("/", 1)[-1] in IAC_NAMES
    )
    return sorted({f.rsplit("/", 1)[0] if "/" in f else "." for f in hits})


def check(
    repo: Path,
    exclude: tuple[str, ...],
    spec_labels: tuple[str, ...],
    graph: ir.Graph,
    unresolved_prefixes: list[str],
    derived: list[str],
) -> list[dict[str, Any]]:
    """The conditions found, in a fixed order; each with `kind`, `detail` and `message`."""
    out: list[dict[str, Any]] = []
    if unresolved_prefixes:
        out.append(
            {
                "kind": "unresolved_route_prefixes",
                "detail": unresolved_prefixes,
                "message": "route prefixes the extractor cannot resolve: "
                + ", ".join(unresolved_prefixes)
                + " (endpoints may look missing and routes orphaned; set pairing.path_constants)",
            }
        )
    containers = [n for n in graph.nodes.values() if n.side == "code" and n.kind == "container"]
    marked = _markers(repo, exclude, spec_labels)
    if len(containers) <= 1 and marked:
        out.append(
            {
                "kind": "fallback_container",
                "detail": marked,
                "message": "one fallback container, but project manifests exist below the root: "
                + ", ".join(marked)
                + " (declare containers)",
            }
        )
    if derived:
        out.append(
            {
                "kind": "test_prefixes_derived",
                "detail": derived,
                "message": "spec id prefixes not in the configured test-name prefixes: "
                + ", ".join(derived)
                + " (derived from the specs for this run; list them in spec_ids.test_name_prefixes)",
            }
        )
    iac = iac_dirs(repo, exclude)
    if iac:
        out.append(
            {
                "kind": "iac_present",
                "detail": iac,
                "message": "infrastructure as code found: "
                + ", ".join(iac)
                + " (set infra_root, and pass --infra-plan for deployment facts)",
            }
        )
    return out


def banner(warnings: list[dict[str, Any]]) -> str:
    n = len(warnings)
    return (
        f"This map was built without configuration; {n} thing{'s' if n != 1 else ''} may be wrong. "
        "Run `ad2v init`."
    )
