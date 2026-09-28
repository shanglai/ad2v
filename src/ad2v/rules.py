"""Extractor rules: built-in rules + optional manifest overlay, canonicalized and hashed (ADR-0012).

Deep-merge semantics: mappings merge key by key (recursively); any other value, including
lists, replaces the base value. `rules_hash` is sha256 of the canonical JSON of the merged
rules, so formatting, comments and line endings never matter, only content does.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from ad2v import ids
from ad2v.resources import python_rules_path


class RulesError(ValueError):
    pass


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = copy.deepcopy(base)
        for k, v in overlay.items():
            out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    return copy.deepcopy(overlay)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RulesError(f"rules file not found: {path}")
    data = yaml.safe_load(ids.read_normalized(path))
    if not isinstance(data, dict):
        raise RulesError(f"rules file must be a mapping: {path}")
    return data


def rules_hash(rules: dict[str, Any]) -> str:
    return ids.sha256_hex(ids.canonical_json({k: v for k, v in rules.items() if not k.startswith("_")}))


def load(base_path: Path | None = None, overlay_path: Path | None = None) -> dict[str, Any]:
    """Merged rules with `_hash` (rules_hash) and `_overlay` (overlay file name or None)."""
    merged = _load_yaml(base_path or python_rules_path())
    if overlay_path is not None:
        merged = deep_merge(merged, _load_yaml(overlay_path))
    merged["_hash"] = rules_hash(merged)
    merged["_overlay"] = overlay_path.name if overlay_path is not None else None
    return merged
