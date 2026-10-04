"""Optional `ad2v.yaml` manifest (format spec §7) and extraction configuration."""

from __future__ import annotations

import re
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
    ".ad2v-extracted",  # proposed prose-spec extractions: ingested only once a human moves them (P4)
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
    test_ref_prefixes: tuple[str, ...] = ("REQ", "CMP", "FR")  # FR: spec-kit (P6.1)
    manifest_path: str | None = None
    # pairing (format spec §6.1)
    pairing_components: dict[str, str] = field(default_factory=dict)  # spec id -> container/component
    path_prefix_map: dict[str, str] = field(default_factory=dict)
    # P7 (issue 70, ADR-0053): values for unresolved route-prefix expressions, by normalized source
    # text ("settings.API_V1_STR" -> "/api/v1"); and the opt-in pydantic Settings-default resolver
    path_constants: dict[str, str] = field(default_factory=dict)
    resolve_settings_defaults: bool = False
    case_insensitive: bool = False
    rules_overlay: Path | None = None
    orphan_policy: str = "auto"  # auto | strict | off (format spec §6.2)
    pairing_links: tuple[tuple[str, str], ...] = ()  # human-confirmed (spec, code qname): manifest_link
    pairing_rejected: tuple[tuple[str, str], ...] = ()  # human-rejected suggestions: never suggested again
    manifest_data: dict[str, Any] = field(default_factory=dict)  # without `llm` (never normative)
    spec_roots: tuple[str, ...] = ()  # ad2v.yaml `spec_root:` (repo-relative), P6.1
    effective_spec_roots: tuple[str, ...] = ()  # what discovery used (set by pipeline.build)
    spec_presets: dict[str, str] = field(default_factory=dict)  # Markdown file -> preset (P6.1)
    spec_markdown: list[dict[str, Any]] = field(default_factory=list)  # ad2v.yaml `spec_markdown:` rules
    llm_data: dict[str, Any] = field(default_factory=dict)  # the `llm:` section (informative, P4)

    @property
    def config_json(self) -> dict[str, Any]:
        """What config_hash covers: the parsed manifest plus the effective defaults that matter."""
        eff: dict[str, Any] = {
            "orphan_policy": self.orphan_policy,
            "spec_roots": list(self.effective_spec_roots),
        }
        if self.spec_presets:
            eff["spec_presets"] = dict(sorted(self.spec_presets.items()))
        return {"effective": eff, "manifest": self.manifest_data}

    @property
    def config_hash(self) -> str:
        return ids.sha256_hex(ids.canonical_json(self.config_json))

    def echo(self) -> dict[str, Any]:
        """Normative echo of the effective configuration, stored in epochs.attrs."""
        return {
            "behavior_emit_all": self.behavior_emit_all,
            "orphan_policy": self.orphan_policy,
            "pairing_case_insensitive": self.case_insensitive,
            "pairing_components": dict(sorted(self.pairing_components.items())),
            "path_prefix_map": dict(sorted(self.path_prefix_map.items())),
            "rules_overlay": self.rules_overlay.name if self.rules_overlay else None,
            "test_ref_prefixes": list(self.test_ref_prefixes),
            "workflow_max_depth": self.workflow_max_depth,
            "workflow_max_steps": self.workflow_max_steps,
            **({"path_constants": dict(sorted(self.path_constants.items()))} if self.path_constants else {}),
            **({"resolve_settings_defaults": True} if self.resolve_settings_defaults else {}),
        }


class ManifestError(ValueError):
    pass


def _norm_rel(p: str) -> str:
    p = p.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") or "."


ORPHAN_POLICIES = ("auto", "strict", "off")


def load(repo: Path, manifest: Path | None = None) -> Config:
    """Load `manifest` or `<repo>/ad2v.yaml` if present; otherwise defaults."""
    path = manifest if manifest is not None else repo / "ad2v.yaml"
    if not path.is_file():
        if manifest is not None:
            raise ManifestError(f"manifest not found: {manifest}")
        return Config()
    text = ids.read_normalized(path)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a mapping")
    cfg = from_data(data, path.parent)
    cfg.manifest_path = path.name
    return cfg


def from_config_json(config_json: dict[str, Any]) -> Config:
    """Rebuild the Config an epoch was extracted with (stored in config_versions)."""
    return from_data(config_json.get("manifest") or {}, None)


def _pairs(raw: Any, key: str) -> tuple[tuple[str, str], ...]:
    out = []
    for i, e in enumerate(raw or []):
        if not isinstance(e, dict) or not e.get("spec") or not e.get("code"):
            raise ManifestError(f"{key}[{i}] needs `spec` and `code`")
        out.append((str(e["spec"]), str(e["code"])))
    return tuple(sorted(set(out)))


def from_data(data: dict[str, Any], base_dir: Path | None) -> Config:
    """Parse manifest data. With base_dir None, file references (rules_overlay) are not checked."""
    cfg = Config()
    cfg.manifest_data = {k: v for k, v in data.items() if k != "llm"}  # llm.* never enters config_hash
    llm = data.get("llm") or {}
    if not isinstance(llm, dict):
        raise ManifestError("llm must be a mapping")
    cfg.llm_data = llm
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
    roots = data.get("spec_root")
    if roots is not None:
        if isinstance(roots, str):
            roots = [roots]
        if not isinstance(roots, list) or not all(isinstance(r, str) and r for r in roots):
            raise ManifestError("spec_root must be a path or a list of paths (relative to the repo)")
        cfg.spec_roots = tuple(_norm_rel(r) for r in roots)
    rules = data.get("spec_markdown") or []
    if not isinstance(rules, list) or not all(
        isinstance(r, dict) and r.get("glob") and r.get("preset") for r in rules
    ):
        raise ManifestError("spec_markdown must be a list of {glob, preset, id_prefix?, …} rules")
    cfg.spec_markdown = [dict(r) for r in rules]
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
    pairing = data.get("pairing") or {}
    if not isinstance(pairing, dict):
        raise ManifestError("pairing must be a mapping")
    comps = pairing.get("components") or {}
    if not isinstance(comps, dict):
        raise ManifestError("pairing.components must map spec ids to container/component names")
    cfg.pairing_components = {str(k): str(v) for k, v in comps.items()}
    prefixes = pairing.get("path_prefix_map") or {}
    if not isinstance(prefixes, dict):
        raise ManifestError("pairing.path_prefix_map must be a mapping")
    cfg.path_prefix_map = {str(k): str(v or "") for k, v in prefixes.items()}
    consts = pairing.get("path_constants") or {}
    if not isinstance(consts, dict):
        raise ManifestError("pairing.path_constants must map expressions to path strings")
    cfg.path_constants = {re.sub(r"\s+", "", str(k)): str(v or "") for k, v in consts.items()}
    cfg.resolve_settings_defaults = bool(pairing.get("resolve_settings_defaults", False))
    cfg.case_insensitive = bool(pairing.get("case_insensitive", False))
    raw_policy = pairing.get("orphan_policy", "auto")
    policy = "off" if raw_policy is False else str(raw_policy)  # YAML 1.1 reads a bare `off` as false
    if policy not in ORPHAN_POLICIES:
        raise ManifestError(f"pairing.orphan_policy must be one of {', '.join(ORPHAN_POLICIES)}")
    cfg.orphan_policy = policy
    cfg.pairing_links = _pairs(pairing.get("links"), "pairing.links")
    cfg.pairing_rejected = _pairs(pairing.get("rejected"), "pairing.rejected")
    if data.get("rules_overlay") and base_dir is not None:
        cfg.rules_overlay = (base_dir / str(data["rules_overlay"])).resolve()
        if not cfg.rules_overlay.is_file():
            raise ManifestError(f"rules_overlay not found: {data['rules_overlay']}")
    return cfg
