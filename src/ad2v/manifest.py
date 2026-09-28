"""Optional `ad2v.yaml` manifest (format spec §7) and extraction configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids

DEFAULT_EXCLUDES = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
)


@dataclass(frozen=True)
class ContainerDecl:
    name: str
    paths: tuple[str, ...]
    kind: str = "service"
    replicas: int = 1
    declared: bool = True  # False when inferred


@dataclass
class Config:
    system_name: str | None = None
    containers: list[ContainerDecl] = field(default_factory=list)
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    behavior_emit_all: bool = False
    workflow_max_depth: int = 12
    workflow_max_steps: int = 5000
    test_ref_prefixes: tuple[str, ...] = ("REQ", "CMP")
    manifest_hash: str | None = None
    manifest_path: str | None = None

    def echo(self) -> dict[str, Any]:
        """Normative echo of the effective configuration, stored in epochs.attrs."""
        return {
            "behavior_emit_all": self.behavior_emit_all,
            "manifest_hash": self.manifest_hash,
            "test_ref_prefixes": list(self.test_ref_prefixes),
            "workflow_max_depth": self.workflow_max_depth,
            "workflow_max_steps": self.workflow_max_steps,
        }


class ManifestError(ValueError):
    pass


def _norm_rel(p: str) -> str:
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") or "."


def load(repo: Path, manifest: Path | None = None) -> Config:
    """Load `manifest` or `<repo>/ad2v.yaml` if present; otherwise defaults."""
    path = manifest if manifest is not None else repo / "ad2v.yaml"
    cfg = Config()
    if not path.is_file():
        if manifest is not None:
            raise ManifestError(f"manifest not found: {manifest}")
        return cfg
    text = ids.read_normalized(path)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a mapping")
    cfg.manifest_hash = ids.content_hash(text)
    cfg.manifest_path = path.name
    system = data.get("system") or {}
    if isinstance(system, str):
        system = {"name": system}
    cfg.system_name = system.get("name")
    for i, c in enumerate(data.get("containers") or []):
        if not isinstance(c, dict) or "name" not in c:
            raise ManifestError(f"containers[{i}] needs a name")
        paths = c.get("paths") or [c.get("path") or c["name"]]
        if isinstance(paths, str):
            paths = [paths]
        cfg.containers.append(
            ContainerDecl(
                name=str(c["name"]),
                paths=tuple(sorted(_norm_rel(p) for p in paths)),
                kind=str(c.get("kind", "service")),
                replicas=int(c.get("replicas", 1)),
            )
        )
    if "exclude" in data:
        cfg.exclude = DEFAULT_EXCLUDES + tuple(str(x) for x in data["exclude"] or [])
    behavior = data.get("behavior") or {}
    cfg.behavior_emit_all = bool(behavior.get("emit_all", False))
    wf = data.get("workflows") or {}
    cfg.workflow_max_depth = int(wf.get("max_depth", cfg.workflow_max_depth))
    cfg.workflow_max_steps = int(wf.get("max_steps", cfg.workflow_max_steps))
    spec_ids = data.get("spec_ids") or {}
    if "test_name_prefixes" in spec_ids:
        cfg.test_ref_prefixes = tuple(str(p).upper() for p in spec_ids["test_name_prefixes"])
    return cfg
