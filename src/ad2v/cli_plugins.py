"""`ad2v extractors list` and `ad2v extractor check` (P8, ADR-0063/0064)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ad2v import plugins
from ad2v.manifest import load as load_manifest


def _out(text: str) -> None:
    sys.stdout.write(text)


def _rows(repo: Path, manifest: Path | None, inspect: bool) -> list[dict[str, Any]]:
    enabled: set[str] = set()
    if repo.is_dir():
        try:
            enabled = set(load_manifest(repo, manifest).extractors_enabled)
        except Exception:  # noqa: BLE001 - a broken manifest still lists what is installed
            enabled = set()
    rows = []
    for d in plugins.discover():
        state = "built-in" if d.builtin else ("enabled" if d.name in enabled else "disabled")
        if d.error:
            state = f"error: {d.error}"
        row: dict[str, Any] = {
            "kind": d.kind,
            "name": d.name,
            "version": None,
            "api_version": None,
            "dist": f"{d.dist or '?'} {d.dist_version or ''}".strip(),
            "target": d.target,
            "state": state,
        }
        # disabled third-party plug-ins are not imported unless asked (ADR-0064)
        if not d.error and (d.builtin or d.name in enabled or inspect):
            try:
                obj = d.load()
                row["version"], row["api_version"] = str(obj.version), str(obj.api_version)
                if d.kind == "framework":
                    row["attaches_to"] = list(obj.attaches_to)
            except plugins.PluginError as e:
                row["state"] = f"{state}; {e}"
        rows.append(row)
    return rows


def cmd_list(a: argparse.Namespace) -> int:
    rows = _rows(Path(a.repo), Path(a.manifest) if a.manifest else None, a.inspect)
    if a.json:
        _out(
            json.dumps({"api_version": plugins.API_VERSION, "plugins": rows}, indent=2, sort_keys=True) + "\n"
        )
        return 0
    _out(f"ad2v plug-in API {plugins.API_VERSION}; groups: ad2v.extractors, ad2v.frameworks\n")
    header = ("kind", "name", "version", "api", "distribution", "state")
    table = [
        (
            r["kind"],
            r["name"],
            r["version"] or "(not loaded)",
            r["api_version"] or "-",
            r["dist"],
            r["state"] + (f" -> {', '.join(r['attaches_to'])}" if r.get("attaches_to") else ""),
        )
        for r in rows
    ]
    widths = [max(len(str(x[i])) for x in [header, *table]) for i in range(len(header))]
    for line in [header, *table]:
        _out("  ".join(str(c).ljust(w) for c, w in zip(line, widths, strict=True)).rstrip() + "\n")
    if any(r["version"] is None and r["state"] == "disabled" for r in rows):
        _out("\ndisabled plug-ins are not imported; --inspect imports them to show version and api.\n")
    _out("enable one in ad2v.yaml (extractors: {enabled: [name]}) or per run with --extractor name.\n")
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    from ad2v.testing.conformance import check, format_text

    result = check(a.name, Path(a.fixture))
    _out(json.dumps(result, indent=2, sort_keys=True) + "\n" if a.json else format_text(result))
    return 0 if result.get("passed") else 1


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    x = sub.add_parser(
        "extractors",
        aliases=["extractor"],
        help="language extractor and framework-pack plug-ins: list, check",
    )
    xs = x.add_subparsers(dest="plugins_cmd", required=True)
    ls = xs.add_parser("list", help="discovered plug-ins (name, version, api, distribution, state)")
    ls.add_argument("--repo", default=".", help="repository whose ad2v.yaml decides enabled/disabled")
    ls.add_argument("--manifest")
    ls.add_argument("--inspect", action="store_true", help="also import disabled plug-ins")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)
    ck = xs.add_parser("check", help="run the conformance kit for a plug-in against a fixture")
    ck.add_argument("name")
    ck.add_argument("--fixture", required=True, help="a small repository directory")
    ck.add_argument("--json", action="store_true", help="machine-readable result")
    ck.set_defaults(func=cmd_check)
