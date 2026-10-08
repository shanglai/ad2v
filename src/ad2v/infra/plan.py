"""Read a Terraform / OpenTofu plan JSON (`terraform show -json tfplan`) (P10 M2, ADR-0074).

ad2v never runs terraform: the human produces the plan and passes the file. Read:

- `planned_values` (root and child modules; `count`/`for_each` already expanded): the resources;
- `configuration`: references between resources and the env-var wiring expressions (module
  variables and outputs are followed);
- `resource_changes`: only the action (create / update / delete / no-op …) and which attributes
  are unknown until apply (`after_unknown`).

Never read: `variables` (they hold sensitive values in clear), `prior_state`, `outputs` /
`output_changes` values, `timestamp`, `relevant_attributes`, `checks`. Anything the plan marks
sensitive (`sensitive_values`) is dropped. Supported: `format_version` 1.x (documented "1.0";
Terraform and OpenTofu emit minor versions such as "1.2", which are backward compatible).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ad2v import ids
from ad2v.infra.model import Resource, Scope, base_path, build_resource, finalize, kind_of, rules

MAX_PLAN_BYTES = 256 * 1024 * 1024
MAX_RESOURCES = 200_000


class InfraInputError(ValueError):
    pass


@dataclass
class PlanRead:
    env: str
    format_version: str
    resources: list[Resource] = field(default_factory=list)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)  # instance address -> attrs
    warnings: list[str] = field(default_factory=list)


def load_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_PLAN_BYTES:
        raise InfraInputError(f"plan file larger than {MAX_PLAN_BYTES // (1024 * 1024)} MB")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise InfraInputError(f"not a plan JSON file: {type(e).__name__}") from None
    if not isinstance(doc, dict):
        raise InfraInputError("not a plan JSON file: the top level is not an object")
    return doc


def content_hash(doc: dict[str, Any]) -> str:
    """Key order, whitespace, BOM and line endings do not matter; the timestamp is ignored."""
    return ids.sha256_hex(ids.canonical_json({k: v for k, v in doc.items() if k != "timestamp"}))


def _scopes(cfg_root: dict[str, Any]) -> dict[str, Scope]:
    out: dict[str, Scope] = {}

    def visit(
        mod: dict[str, Any], path: str, parent: Scope | None, call_name: str | None, depth: int
    ) -> None:
        if depth > 16 or not isinstance(mod, dict):
            return
        sc = Scope(path=path, parent=parent, call_name=call_name)
        for r in mod.get("resources") or []:
            if (
                isinstance(r, dict)
                and r.get("mode", "managed") == "managed"
                and r.get("type")
                and r.get("name")
            ):
                sc.resources[f"{r['type']}.{r['name']}"] = r
        for name, call in sorted((mod.get("module_calls") or {}).items()):
            if isinstance(call, dict):
                sc.calls[name] = call
        for name, o in sorted((mod.get("outputs") or {}).items()):
            if isinstance(o, dict) and isinstance(o.get("expression"), dict):
                sc.outputs[name] = o["expression"]
        for name, v in (mod.get("variables") or {}).items():
            if isinstance(v, dict) and v.get("sensitive"):
                sc.sensitive_vars.add(name)
        out[path] = sc
        for name, call in sorted(sc.calls.items()):
            child = f"{path}.module.{name}" if path else f"module.{name}"
            visit(call.get("module") or {}, child, sc, name, depth + 1)

    visit(cfg_root or {}, "", None, None, 0)
    return out


def read(doc: dict[str, Any], env: str) -> PlanRead:
    fv = str(doc.get("format_version", ""))
    if fv.split(".", 1)[0] != "1":
        raise InfraInputError(f"unsupported plan format_version {fv!r} (ad2v reads 1.x)")
    out = PlanRead(env, fv)
    scopes = _scopes((doc.get("configuration") or {}).get("root_module") or {})
    if "" not in scopes:
        scopes[""] = Scope(path="")
    known_kinds = {
        (sc.path + "." if sc.path else "") + addr: kind_of(cfg.get("type", ""))
        for sc in scopes.values()
        for addr, cfg in sc.resources.items()
    }
    changes: dict[str, dict[str, Any]] = {}
    for rc in doc.get("resource_changes") or []:
        if isinstance(rc, dict) and isinstance(rc.get("address"), str) and isinstance(rc.get("change"), dict):
            changes[rc["address"]] = rc["change"]

    count = 0

    def visit(mod: dict[str, Any], depth: int) -> None:
        nonlocal count
        if depth > 16 or not isinstance(mod, dict):
            return
        maddr = str(mod.get("address") or "")
        if maddr:
            bp = base_path(maddr)
            parent_path, _, last = (
                bp.rpartition(".module.") if ".module." in bp else ("", "", bp[len("module.") :])
            )
            psc = scopes.get(parent_path)
            call = psc.calls.get(last) if psc else None
            src = str((call or {}).get("source") or (call or {}).get("resolved_source") or "")
            out.modules[maddr] = {"source": "plan", "remote": bool(src) and not src.startswith(("./", "../"))}
        for r in mod.get("resources") or []:
            if not isinstance(r, dict) or r.get("mode", "managed") != "managed":
                continue
            addr, rtype, name = r.get("address"), r.get("type"), r.get("name")
            if not (isinstance(addr, str) and isinstance(rtype, str) and isinstance(name, str)):
                continue
            count += 1
            if count > MAX_RESOURCES:
                raise InfraInputError(f"more than {MAX_RESOURCES} resources in one plan")
            sc = scopes.get(base_path(maddr)) or scopes[""]
            cfg = sc.resources.get(f"{rtype}.{name}", {})
            ch = changes.get(addr, {})
            res = build_resource(
                env=env,
                address=addr,
                module=maddr,
                rtype=rtype,
                name=name,
                provider=str(r.get("provider_name") or ""),
                values=r.get("values") if isinstance(r.get("values"), dict) else {},
                exprs=cfg.get("expressions") if isinstance(cfg.get("expressions"), dict) else {},
                sensitive=r.get("sensitive_values", {}),
                unknown=ch.get("after_unknown", {}),
                scope=sc,
                scopes=scopes,
                source="plan",
                known_kinds=known_kinds,
            )
            acts = ch.get("actions")
            if isinstance(acts, list) and all(isinstance(a, str) for a in acts):
                res.action = "+".join(acts)
            if r.get("index") is not None and not cfg:
                out.warnings.append(f"{addr}: no configuration block found")
            out.resources.append(res)
        for cm in mod.get("child_modules") or []:
            visit(cm, depth + 1)

    visit(((doc.get("planned_values") or {}).get("root_module")) or {}, 0)
    unknown_types = sorted({r.type for r in out.resources if r.type not in rules()["types"]})
    if unknown_types:
        out.warnings.append("resource types kept as infra_other: " + ", ".join(unknown_types[:20]))
    finalize(out.resources)
    out.resources.sort(key=lambda r: r.address)
    return out
