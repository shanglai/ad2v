"""Identity, hashing and normalization rules (normative; format spec §4).

Everything in this module must produce byte-identical results on every platform.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePath
from typing import Any

ID_HEX_LEN = 20
# Spec IDs (format spec §3.6). `REQ-X001`: the reserved range for LLM-proposed items (P4, ADR-0031).
# P6.1 (ADR-0048): optional `<namespace>:` (spec-kit feature slug) and `.n` sub-id (Kiro criteria)
SPEC_ID_PATTERN = r"(?:[a-z0-9][a-z0-9-]*:)?[A-Z][A-Z0-9]*-X?[0-9]+(?:\.[0-9]+)?"
UTF8_BOM = b"\xef\xbb\xbf"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_bytes(data: bytes) -> str:
    """Decode repository bytes into normalized text.

    Strips one leading UTF-8 BOM, decodes as UTF-8 (undecodable bytes become U+FFFD, which is
    deterministic), and normalizes CRLF and lone CR line endings to LF.
    """
    if data.startswith(UTF8_BOM):
        data = data[len(UTF8_BOM) :]
    return normalize_text(data.decode("utf-8", errors="replace"))


def normalize_text(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_normalized(path: Path) -> str:
    return normalize_bytes(path.read_bytes())


def rel_posix(path: Path | str, root: Path | str) -> str:
    """Repo-relative path with forward slashes, no leading './'."""
    rel = PurePath(Path(path).resolve().relative_to(Path(root).resolve())).as_posix()
    return "" if rel == "." else rel


def _short(prefix: str, payload: str) -> str:
    return prefix + sha256_hex(payload)[:ID_HEX_LEN]


def node_id(side: str, kind: str, qualified_name: str) -> str:
    """Stable node identity: depends on what a node is, never on its content."""
    return _short("n_", f"{side}|{kind}|{qualified_name}")


def workflow_id(side: str, entry_node_id: str, source: str) -> str:
    return _short("w_", f"{side}|{entry_node_id}|{source}")


def epoch_id(
    parent_epoch_id: str | None,
    repo_tree_hash: str,
    spec_tree_hash: str,
    rules_hash: str,
    config_hash: str,
    test_results_hash: str,
) -> str:
    """Epoch identity covers every input that shapes the output (ADR-0010, ADR-0012)."""
    parts = [
        parent_epoch_id or "",
        repo_tree_hash,
        spec_tree_hash,
        rules_hash,
        config_hash,
        test_results_hash,
    ]
    return _short("e_", "|".join(parts))


def link_id(spec_node_id: str | None, code_node_id: str | None, method: str) -> str:
    return _short("l_", f"{spec_node_id or ''}|{code_node_id or ''}|{method}")


def content_hash(text: str) -> str:
    """Hash of normalized content (full 64 hex chars)."""
    return sha256_hex(normalize_text(text))


def canonical_json(obj: Any) -> str:
    """The one JSON serialization used for hashing, storage and dumps."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def attrs_hash(kind: str, name: str, attrs: Mapping[str, Any]) -> str:
    """content_hash for nodes that have no source text of their own."""
    return sha256_hex(canonical_json({"kind": kind, "name": name, "attrs": attrs}))


def subtree_hash(own_content_hash: str, children: Iterable[tuple[str, str]]) -> str:
    """Merkle hash: own content hash plus (child_id, child_subtree_hash) sorted by child id."""
    lines = [own_content_hash] + [f"{cid}:{h}" for cid, h in sorted(children)]
    return sha256_hex("\n".join(lines))


def tree_hash(entries: Mapping[str, str]) -> str:
    """Hash of a file tree given {relative_posix_path: content_hash}."""
    return sha256_hex("\n".join(f"{p}\t{h}" for p, h in sorted(entries.items())))
