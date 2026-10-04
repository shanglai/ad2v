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


class RulesError(ValueError):
    pass


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = copy.deepcopy(base)
        for k, v in overlay.items():
            out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    return copy.deepcopy(overlay)


def pack_merge(base: Any, fragment: Any) -> Any:
    """Framework-pack merge (ADR-0063): mappings merge key by key, lists are unioned (base items
    first, then new items in fragment order), any other value is replaced."""
    if isinstance(base, dict) and isinstance(fragment, dict):
        out = copy.deepcopy(base)
        for k, v in fragment.items():
            out[k] = pack_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(fragment, list):
        out_list = copy.deepcopy(base)
        for item in fragment:
            if item not in out_list:
                out_list.append(copy.deepcopy(item))
        return out_list
    return copy.deepcopy(fragment)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RulesError(f"rules file not found: {path}")
    data = yaml.safe_load(ids.read_normalized(path))
    if not isinstance(data, dict):
        raise RulesError(f"rules file must be a mapping: {path}")
    return data


def rules_hash(rules: dict[str, Any]) -> str:
    return ids.sha256_hex(ids.canonical_json({k: v for k, v in rules.items() if not k.startswith("_")}))


def load(base_path: Path | None = None, overlay_path: Path | None = None) -> dict[str, Any]:
    """The epoch rules of a run with only the built-in plug-ins active (P8, ADR-0065): the Python
    extractor's rules (`base_path` replaces python.yaml), the built-in framework pack's fragment,
    the overlay, and the `plugins` identity records."""
    from ad2v.plugins import default_epoch_rules

    if overlay_path is not None:
        load_yaml(overlay_path)  # fail early with RulesError on a missing or malformed overlay
    return default_epoch_rules(base_path, overlay_path)
