"""Visual tokens (docs/spec/visual-tokens-v0.2.md).

Normative: STATUS_STYLES, the status -> (token name, line style, fill, decoration, weight)
mapping. Status must stay readable with color removed, so no two statuses may share the same
non-color signature. Informative: the palettes in schema/themes/{dark,light}.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from typing import Any

from ad2v import ir
from ad2v.resources import schema_dir

LINE_STYLES = ("solid", "dotted", "dashed", "dash_dot")
FILLS = ("tinted", "hollow")
DECORATIONS = ("none", "emphasis", "warning_badge", "clock_badge")
WEIGHTS = ("regular", "thin")
THEMES = ("dark", "light")


@dataclass(frozen=True)
class StatusStyle:
    token: str  # key into theme["status"]
    line: str
    fill: str
    decoration: str
    weight: str = "regular"

    @property
    def signature(self) -> tuple[str, str, str, str]:
        """Everything except color: must be unique per status."""
        return (self.line, self.fill, self.decoration, self.weight)


STATUS_STYLES: dict[str, StatusStyle] = {
    "specified": StatusStyle("status.specified", "dotted", "tinted", "none"),
    "implemented": StatusStyle("status.implemented", "solid", "tinted", "none"),
    "verified": StatusStyle("status.verified", "solid", "tinted", "emphasis"),
    "drift": StatusStyle("status.drift", "solid", "tinted", "warning_badge"),
    "orphan": StatusStyle("status.orphan", "dashed", "tinted", "none"),
    "missing": StatusStyle("status.missing", "dotted", "hollow", "none"),
    "needs_review": StatusStyle("status.needs_review", "dash_dot", "tinted", "none"),
    "stale": StatusStyle("status.stale", "solid", "tinted", "clock_badge"),
    "none": StatusStyle("status.none", "solid", "tinted", "none", "thin"),
}
assert set(STATUS_STYLES) == set(ir.NODE_STATUSES)

DASHARRAY = {"solid": None, "dotted": "1.5 4.5", "dashed": "7 5", "dash_dot": "9 4 1.5 4"}

# Overlay badges (P5, visual tokens §6). The glyph is the non-color signature; color reinforces it.
OVERLAY_BADGES: dict[str, tuple[str, str, str]] = {  # name -> (glyph, color token, text token)
    "ai": ("AI", "badge.ai", "badge.ai_text"),  # LLM drift in effective mode
    "suggestion": ("?", "badge.suggestion", "badge.suggestion_text"),  # open link suggestion
    "diff_added": ("+", "diff.added", "diff.badge_text"),
    "diff_removed": ("\u2212", "diff.removed", "diff.badge_text"),  # a translucent ghost as well
    "diff_renamed": ("\u21ba", "diff.renamed", "diff.badge_text"),
    "diff_transition": ("\u2192", "diff.transition", "diff.badge_text"),
}


def token(theme: dict[str, Any], dotted: str) -> Any:
    cur: Any = theme
    for part in dotted.split("."):
        cur = cur[part]
    return cur


@cache
def load_theme(name: str) -> dict[str, Any]:
    if name not in THEMES:
        raise ValueError(f"unknown theme {name!r}")
    return json.loads((schema_dir() / "themes" / f"{name}.json").read_text(encoding="utf-8"))


def status_color(theme: dict[str, Any], status: str) -> dict[str, str]:
    return theme["status"][STATUS_STYLES[status].token.split(".", 1)[1]]


# --- WCAG 2.x contrast --------------------------------------------------------------------


def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color!r}")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
