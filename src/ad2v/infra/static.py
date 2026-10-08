"""Read `.tf` files statically (P10 M3, ADR-0075): for history and when no plan is supplied.

Parser: python-hcl2 (MIT; lark MIT, regex Apache-2.0 AND CNRI-Python), pinned. Nothing is
evaluated. The result has the same shape as a plan read, with these limits:

- `count` / `for_each` are not expanded: one node, `attrs.multiplicity = "unresolved"`;
- local modules (`./…`, `../…`) are followed one level; deeper calls and remote modules are
  recorded as `infra_module` nodes (`followed: false` / `remote: true`);
- variables stay unresolved; their defaults are never stored (sensitive or not);
- only literal attribute values are known; everything computed is unknown;
- `locals` are followed for references; `dynamic` blocks and `jsonencode(...)` are opaque.

One static environment per infra root: `default` for a single root, else the root folder's name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ad2v import ids
from ad2v.infra.model import Resource, Scope, build_resource, finalize, kind_of
from ad2v.infra.plan import InfraInputError

MAX_TF_BYTES = 4 * 1024 * 1024  # per file
MAX_TF_FILES = 2000
REF_RE = re.compile(r"(?<![\w.\"'\-])([A-Za-z_][\w-]*(?:\[[^\]]*\])?(?:\.[A-Za-z_][\w-]*(?:\[[^\]]*\])?)+)")
QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
INTERP_RE = re.compile(r"\$\{(.*?)\}", re.S)


@dataclass
class StaticRead:
    env: str
    root: str
    resources: list[Resource] = field(default_factory=list)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # repo-relative path -> content hash
    warnings: list[str] = field(default_factory=list)


def _unquote(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _refs_in(text: str) -> list[str]:
    inner = (
        INTERP_RE.findall(text) if text.startswith('"') else [text[2:-1] if text.startswith("${") else text]
    )
    found: set[str] = set()
    for chunk in inner:
        for m in REF_RE.finditer(QUOTED_RE.sub('""', chunk)):
            tok = m.group(1)
            head = tok.split(".", 1)[0].split("[", 1)[0]
            if head in ("var", "module", "local", "data") or "_" in head:
                found.add(tok)
    return sorted(found)


def _leaf(v: Any) -> tuple[Any, Any]:
    """(value or None, expression leaf) for one attribute value from python-hcl2."""
    if isinstance(v, (bool, int, float)):
        return v, {"constant_value": v}
    if isinstance(v, str):
        if "${" not in v:
            lit = _unquote(v)
            return lit, {"constant_value": lit}
        refs = _refs_in(v)
        return None, ({"references": refs} if refs else {"references": []})
    return None, None


def _trees(body: Any, depth: int = 0) -> tuple[Any, Any]:
    """python-hcl2 body -> (values, exprs) in the plan's shapes (blocks are lists of objects)."""
    if depth > 32:
        return None, None
    if isinstance(body, dict):
        vals: dict[str, Any] = {}
        exprs: dict[str, Any] = {}
        for k, v in body.items():
            if k == "__is_block__":
                continue
            key = _unquote(k)
            if isinstance(v, (dict, list)):
                vv, ee = _trees(v, depth + 1)
            else:
                vv, ee = _leaf(v)
            if vv is not None:
                vals[key] = vv
            if ee is not None:
                exprs[key] = ee
        return vals, exprs
    if isinstance(body, list):
        pairs = [_trees(x, depth + 1) if isinstance(x, (dict, list)) else _leaf(x) for x in body]
        return [p[0] for p in pairs if p[0] is not None], [p[1] for p in pairs if p[1] is not None]
    return _leaf(body)


def _blocks(doc: dict[str, Any], kind: str) -> list[tuple[list[str], dict[str, Any]]]:
    """(labels, body) of every `kind` block (resource "t" "n" -> (['t','n'], body))."""
    out = []
    for item in doc.get(kind, []) or []:
        if not isinstance(item, dict):
            continue
        for l1, b1 in item.items():
            if kind in ("resource", "data"):
                if isinstance(b1, dict):
                    for l2, b2 in b1.items():
                        if isinstance(b2, dict):
                            out.append(([_unquote(l1), _unquote(l2)], b2))
            elif isinstance(b1, dict):
                out.append(([_unquote(l1)], b1))
    return out


def parse_dir(repo: Path, rel_dir: str, read: Any) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Merge every `*.tf` in one directory (not recursive). Returns (doc, files, warnings)."""
    import hcl2  # local import: only static reads need the parser

    base = repo / rel_dir if rel_dir not in ("", ".") else repo
    merged: dict[str, list[Any]] = {}
    files: dict[str, str] = {}
    warnings: list[str] = []
    if not base.is_dir():
        return {}, files, [f"{rel_dir}: not a directory"]
    paths = sorted(p for p in base.iterdir() if p.suffix == ".tf" and p.is_file() and not p.is_symlink())
    for p in paths[:MAX_TF_FILES]:
        rel = p.relative_to(repo).as_posix()
        if p.stat().st_size > MAX_TF_BYTES:
            warnings.append(f"{rel}: larger than {MAX_TF_BYTES // (1024 * 1024)} MB, skipped")
            continue
        text = read(rel)
        files[rel] = ids.content_hash(text)
        try:
            doc = hcl2.loads(text)
        except Exception as e:  # noqa: BLE001 - a broken file is reported, never fatal
            warnings.append(f"{rel}: not parsed ({type(e).__name__})")
            continue
        for k, v in doc.items():
            if isinstance(v, list):
                merged.setdefault(k, []).extend(v)
    return merged, files, warnings


def read_root(
    repo: Path, root: str, env: str, read: Any, plan_scopes_kinds: dict[str, str] | None = None
) -> StaticRead:
    out = StaticRead(env, root)
    doc, files, warn = parse_dir(repo, root, read)
    out.files.update(files)
    out.warnings += warn
    scopes: dict[str, Scope] = {}
    bodies: dict[str, dict[str, tuple[str, str, dict[str, Any]]]] = {}  # scope path -> addr -> (t, n, body)

    def make_scope(
        d: dict[str, Any], path: str, parent: Scope | None, call: str | None, folder: str, depth: int
    ) -> None:
        sc = Scope(path=path, parent=parent, call_name=call)
        bodies[path] = {}
        for (t, n), body in _blocks(d, "resource"):
            _, ex = _trees(body)
            sc.resources[f"{t}.{n}"] = {"type": t, "name": n, "expressions": ex}
            bodies[path][f"{t}.{n}"] = (t, n, body)
        for item in d.get("locals", []) or []:
            if isinstance(item, dict):
                _, ex = _trees(item)
                for k, v in (ex or {}).items():
                    sc.outputs[f"__local__.{k}"] = v
        for (name,), body in _blocks(d, "variable"):
            if body.get("sensitive") is True:
                sc.sensitive_vars.add(name)
        for (name,), body in _blocks(d, "output"):
            _, ex = _trees(body)
            if isinstance(ex, dict) and "value" in ex:
                sc.outputs[name] = ex["value"]
        scopes[path] = sc
        for (name,), body in _blocks(d, "module"):
            _, ex = _trees(body)
            sc.calls[name] = {"expressions": ex or {}}
            src = _unquote(str(body.get("source", "")))
            maddr = f"{path}.module.{name}" if path else f"module.{name}"
            local = src.startswith(("./", "../"))
            multi = "count" in body or "for_each" in body
            out.modules[maddr] = {
                "source": "static",
                "remote": not local,
                "followed": local and depth == 0,
                **({"multiplicity": "unresolved"} if multi else {}),
            }
            if local and depth == 0:
                sub = (Path(folder) / src).as_posix()
                sub = _norm(sub)
                if sub is None:
                    out.warnings.append(f"{maddr}: source outside the repository, not followed")
                    out.modules[maddr]["followed"] = False
                    continue
                cdoc, cfiles, cwarn = parse_dir(repo, sub, read)
                out.files.update(cfiles)
                out.warnings += cwarn
                make_scope(cdoc, maddr, sc, name, sub, depth + 1)
            elif local:
                out.warnings.append(f"{maddr}: nested local module not followed (one level)")

    make_scope(doc, "", None, None, root, 0)
    known = {
        (sc.path + "." if sc.path else "") + a: kind_of(c["type"])
        for sc in scopes.values()
        for a, c in sc.resources.items()
    }
    for path in sorted(bodies):
        for addr in sorted(bodies[path]):
            t, n, body = bodies[path][addr]
            vals, ex = _trees(body)
            sc = scopes[path]
            res = build_resource(
                env=env,
                address=(path + "." if path else "") + addr,
                module=path,
                rtype=t,
                name=n,
                provider=t.split("_", 1)[0],
                values=vals if isinstance(vals, dict) else {},
                exprs=ex if isinstance(ex, dict) else {},
                sensitive={},
                unknown={},
                scope=sc,
                scopes=scopes,
                source="static",
                known_kinds=known,
            )
            if "count" in body or "for_each" in body:
                res.attrs["multiplicity"] = "unresolved"
            out.resources.append(res)
    finalize(out.resources)
    out.resources.sort(key=lambda r: r.address)
    return out


def _norm(p: str) -> str | None:
    parts: list[str] = []
    for seg in p.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def env_names(roots: list[str]) -> dict[str, str]:
    """infra root -> static environment name."""
    if len(roots) == 1:
        return {roots[0]: "default"}
    out: dict[str, str] = {}
    used: set[str] = set()
    for r in sorted(roots):
        name = re.sub(r"[^A-Za-z0-9_-]", "-", r.rstrip("/").rsplit("/", 1)[-1]) or "root"
        cand, i = name, 2
        while cand in used:
            cand, i = f"{name}-{i}", i + 1
        used.add(cand)
        out[r] = cand
    return out


__all__ = ["InfraInputError", "StaticRead", "env_names", "read_root"]
