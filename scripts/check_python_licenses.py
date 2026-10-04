"""Python license gate (P8 M4): no copyleft in ad2v's installed dependency closure.

Walks the runtime requirements of the installed `ad2v` distribution transitively (extras only with
--extras), reads each distribution's license metadata (License-Expression, License, classifiers)
and fails on copyleft families (GPL, LGPL, AGPL, MPL, EPL, CDDL, CC-BY-SA, OFL) or on a banned
package (`certifi`, MPL-2.0: rules out requests, httpx, provider SDKs and the official MCP SDK).
Unknown licenses fail too, unless listed in KNOWN below after a manual check.

    python scripts/check_python_licenses.py [--extras dev] [--json]

Stdlib only; run it in the environment where ad2v is installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib import metadata

COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|CDDL|CC-BY-SA|OFL|GNU|Mozilla|Eclipse Public)\b", re.I)
BANNED = {"certifi": "MPL-2.0; ad2v keeps HTTP on the stdlib (docs/dependencies.md)"}
# distributions whose metadata does not state a license clearly, checked by hand
KNOWN: dict[str, str] = {}
PERMISSIVE = re.compile(
    r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|Unlicense|0BSD|Zlib|BlueOak|CC0)\b", re.I
)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    expr = md.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [
        c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    if classifiers:
        return " / ".join(classifiers)
    lic = (md.get("License") or "").strip()
    return lic.splitlines()[0][:80] if lic else ""


def closure(root: str, extras: set[str]) -> dict[str, metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [(root, extras)]
    while todo:
        name, ex = todo.pop()
        key = _norm(name)
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # an optional dependency for another platform / Python version
        seen[key] = dist
        for req in dist.requires or []:
            m = re.match(r"^([A-Za-z0-9_.\-]+)", req)
            if not m:
                continue
            marker = req.split(";", 1)[1] if ";" in req else ""
            if "extra" in marker:
                wanted = re.findall(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
                if not (key == _norm(root) and set(wanted) & ex):
                    continue
                marker = re.sub(r"(and|or)?\s*extra\s*==\s*['\"][^'\"]+['\"]", "", marker).strip()
            if marker and not _marker_ok(marker):
                continue
            todo.append((m.group(1), set()))
    return seen


def _marker_ok(marker: str) -> bool:
    try:
        from packaging.markers import Marker  # usually present; fall back to "applies"

        return bool(Marker(marker).evaluate())
    except Exception:  # noqa: BLE001
        return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="ad2v")
    ap.add_argument("--extras", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    dists = closure(a.root, set(a.extras))
    if _norm(a.root) not in dists:
        sys.stderr.write(f"{a.root} is not installed in this environment\n")
        return 2
    rows, problems = [], []
    for key in sorted(dists):
        d = dists[key]
        lic = KNOWN.get(key) or license_of(d)
        rows.append({"name": d.metadata["Name"], "version": d.version, "license": lic})
        if key in BANNED:
            problems.append(f"{key}: banned ({BANNED[key]})")
        elif COPYLEFT.search(lic) and not re.search(r"\bor\b.*\b(MIT|Apache|BSD)", lic, re.I):
            problems.append(f"{key} {d.version}: copyleft license {lic!r}")
        elif not PERMISSIVE.search(lic):
            problems.append(f"{key} {d.version}: unknown license {lic!r} (check by hand, then add to KNOWN)")
    if a.json:
        print(json.dumps({"packages": rows, "problems": problems}, indent=2))
    else:
        for r in rows:
            print(f"  {r['name']:28s} {r['version']:12s} {r['license']}")
        print(
            f"{len(rows)} distribution(s) in the closure of {a.root}"
            + (f" [{','.join(a.extras)}]" if a.extras else "")
        )
    if problems:
        for p in problems:
            sys.stderr.write(f"license gate: {p}\n")
        return 1
    print("licenses OK: no copyleft, no banned packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
