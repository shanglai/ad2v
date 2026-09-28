"""`ad2v preview-tokens`: one self-contained static HTML page (inline SVG + CSS, no external assets).

Shows every glyph base shape x every status in the dark and light themes side by side, a
grayscale copy of the dark panel (status must survive without color), and the severity ramp.
"""

from __future__ import annotations

from html import escape
from typing import Any

from ad2v import __version__, glyphs, ir, tokens

W, H = 84, 64

# Base-shape outlines in an 84x64 box (drawn as a single path/element string, stroke+fill set later).
SHAPES: dict[str, str] = {
    "rounded_box": '<rect x="16" y="14" width="52" height="36" rx="8"/>',
    "cylinder": '<path d="M18 19 v26 a24 7 0 0 0 48 0 v-26 a24 7 0 0 0 -48 0 a24 7 0 0 0 48 0"/>',
    "tube": '<path d="M22 20 h40 a7 12 0 0 1 0 24 h-40 a7 12 0 0 1 0 -24 a7 12 0 0 1 0 24"/>',
    "trapezoid": '<path d="M26 15 h32 l12 34 h-56 z"/>',
    "hexagon": '<path d="M42 10 l19 11 v22 l-19 11 l-19 -11 v-22 z"/>',
    "diamond": '<path d="M42 9 l24 23 l-24 23 l-24 -23 z"/>',
    "ring": '<path fill-rule="evenodd" d="M42 12 a20 20 0 1 0 0.01 0 z M42 23 a9 9 0 1 0 0.01 0 z"/>',
    "port_notch": '<path d="M14 16 h44 v9 h12 v14 h-12 v9 h-44 z"/>',
    "folded_sheet": '<path d="M22 10 h30 l12 12 v33 h-42 z M52 10 v12 h12"/>',
    "cloud": '<path d="M26 47 a11 11 0 0 1 1 -22 a15 15 0 0 1 28 -5 a12 12 0 0 1 5 27 z"/>',
}
assert set(SHAPES) == set(glyphs.BASE_SHAPES)

STATUS_ORDER = [
    s
    for s in (
        "specified",
        "implemented",
        "verified",
        "drift",
        "orphan",
        "missing",
        "needs_review",
        "stale",
        "none",
    )
]
assert set(STATUS_ORDER) == set(ir.NODE_STATUSES)


def _styled(shape: str, stroke: str, fill: str, width: float, dash: str | None, extra: str = "") -> str:
    tag_end = shape.index(" ")
    attrs = f' stroke="{stroke}" fill="{fill}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    return shape[:tag_end] + attrs + extra + shape[tag_end:]


def glyph_svg(base: str, status: str, theme: dict[str, Any]) -> str:
    st = tokens.STATUS_STYLES[status]
    col = tokens.status_color(theme, status)
    width = 1.2 if st.weight == "thin" else 2.2
    fill = "none" if st.fill == "hollow" else col["fill"]
    dash = tokens.DASHARRAY[st.line]
    shape = SHAPES[base]
    parts = []
    if st.decoration == "emphasis":
        emph = theme["emphasis"]
        if emph["kind"] == "halo":
            parts.append(
                _styled(shape, emph["color"], "none", emph["width"], None, f' opacity="{emph["opacity"]}"')
            )
            parts.append(_styled(shape, col["stroke"], fill, width + 0.6, dash))
        else:
            parts.append(
                _styled(shape, col["stroke"], fill, width, dash, f' filter="url(#glow-{theme["name"]})"')
            )
    else:
        parts.append(_styled(shape, col["stroke"], fill, width, dash))
    badge = theme["badge"]
    if st.decoration == "warning_badge":
        parts.append(
            f'<path d="M69 3 l10 17 h-20 z" fill="{badge["warning"]}"/>'
            f'<text x="69" y="18" text-anchor="middle" font-size="11" font-weight="700" '
            f'fill="{badge["warning_text"]}" font-family="system-ui,sans-serif">!</text>'
        )
    elif st.decoration == "clock_badge":
        parts.append(
            f'<circle cx="72" cy="12" r="7" fill="none" stroke="{badge["clock"]}" stroke-width="1.6"/>'
            f'<path d="M72 8 v4 l3 2" fill="none" stroke="{badge["clock"]}" stroke-width="1.6" stroke-linecap="round"/>'
        )
    label = f"{base} / {status}"
    return (
        f'<svg viewBox="0 0 {W} {H}" width="66" height="50" role="img" aria-label="{escape(label)}">'
        f"<title>{escape(label)}</title>{''.join(parts)}</svg>"
    )


def _defs(themes: list[dict[str, Any]]) -> str:
    out = []
    for t in themes:
        e = t["emphasis"]
        if e["kind"] == "glow":
            out.append(
                f'<filter id="glow-{t["name"]}" x="-40%" y="-40%" width="180%" height="180%">'
                f'<feGaussianBlur in="SourceGraphic" stdDeviation="{e["radius"] / 2}" result="b"/>'
                f'<feFlood flood-color="{e["color"]}" flood-opacity="{e["opacity"]}"/>'
                '<feComposite in2="b" operator="in" result="g"/>'
                '<feMerge><feMergeNode in="g"/><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge>'
                "</filter>"
            )
    return f'<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{"".join(out)}</defs></svg>'


def _line_sample(status: str, theme: dict[str, Any]) -> str:
    st = tokens.STATUS_STYLES[status]
    col = tokens.status_color(theme, status)
    dash = tokens.DASHARRAY[st.line]
    d = f' stroke-dasharray="{dash}"' if dash else ""
    w = 1.2 if st.weight == "thin" else 2.2
    return (
        f'<svg viewBox="0 0 44 10" width="44" height="10" aria-hidden="true">'
        f'<line x1="3" y1="5" x2="41" y2="5" stroke="{col["stroke"]}" stroke-width="{w}" '
        f'stroke-linecap="round"{d}/></svg>'
    )


def _panel(theme: dict[str, Any], extra_class: str = "", title: str | None = None) -> str:
    name = theme["name"]
    head = "".join(
        f'<th scope="col"><span class="st">{escape(s.replace("_", " "))}</span>'
        f'{_line_sample(s, theme)}<span class="sub">{escape(_describe(s))}</span></th>'
        for s in STATUS_ORDER
    )
    rows = []
    for base in glyphs.BASE_SHAPES:
        kinds = sorted({k for k, (b, _v) in glyphs.KIND_SHAPES.items() if b == base})
        cells = "".join(f"<td>{glyph_svg(base, s, theme)}</td>" for s in STATUS_ORDER)
        rows.append(
            f'<tr><th scope="row"><span class="shape">{escape(base.replace("_", " "))}</span>'
            f'<span class="sub">{escape(", ".join(kinds))}</span></th>{cells}</tr>'
        )
    ramp = "".join(
        f'<div class="sw" style="background:{c}"><span>{i + 1}</span></div>'
        for i, c in enumerate(theme["severity_ramp"])
    )
    t = title or f"{name.capitalize()} theme"
    return f"""
<section class="panel {extra_class}" style="--bg:{theme["background"]};--surface:{theme["surface"]};--grid:{theme["grid"]};--text:{theme["text"]};--muted:{theme["text_muted"]}">
  <header><h2>{escape(t)}</h2><p>{escape(theme["description"])}</p></header>
  <div class="scroll"><table>
    <thead><tr><th scope="col" class="corner">base shape<span class="sub">node kinds</span></th>{head}</tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
  <div class="ramp"><h3>Severity ramp</h3><div class="sws">{ramp}</div><p class="sub">1 = lowest, 5 = highest attrs.severity bucket</p></div>
</section>"""


def _describe(status: str) -> str:
    st = tokens.STATUS_STYLES[status]
    bits = [st.line.replace("_", "-")]
    if st.fill == "hollow":
        bits.append("hollow")
    if st.decoration != "none":
        bits.append(
            {"emphasis": "glow/halo", "warning_badge": "warning badge", "clock_badge": "clock badge"}[
                st.decoration
            ]
        )
    if st.weight == "thin":
        bits.append("thin")
    return " + ".join(bits)


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#1d2129;color:#e8ecf2;font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.page{max-width:1880px;margin:0 auto;padding:28px 16px 48px}
.intro h1{margin:0 0 6px;font-size:22px;font-weight:650;letter-spacing:.2px}
.intro p{margin:0 0 4px;color:#b8c1ce;max-width:980px}
.grid{display:flex;flex-wrap:wrap;gap:20px;margin-top:22px}
.panel{flex:1 1 820px;min-width:0;background:var(--bg);color:var(--text);border-radius:14px;padding:18px 18px 16px;
  border:1px solid color-mix(in srgb,var(--grid) 80%,transparent)}
.panel header h2{margin:0;font-size:16px;font-weight:650}
.panel header p{margin:2px 0 12px;color:var(--muted);font-size:12.5px}
.scroll{overflow-x:auto}
table{border-collapse:separate;border-spacing:0}
th,td{padding:3px 3px;text-align:center;vertical-align:middle}
thead th{font-weight:600;font-size:12px;padding-bottom:8px;border-bottom:1px solid var(--grid)}
thead th svg{display:block;margin:4px auto 2px}
tbody th{text-align:left;padding-right:10px;white-space:nowrap;border-right:1px solid var(--grid)}
tbody tr+tr td,tbody tr+tr th{border-top:1px solid color-mix(in srgb,var(--grid) 55%,transparent)}
td svg{display:block}
.st{display:block;text-transform:none}
.shape{display:block;font-weight:600;font-size:12.5px}
.sub{display:block;color:var(--muted);font-size:10.5px;font-weight:400;max-width:96px;white-space:normal}
.corner{text-align:left}
.ramp{margin-top:14px;padding-top:10px;border-top:1px solid var(--grid)}
.ramp h3{margin:0 0 6px;font-size:12.5px;font-weight:600}
.sws{display:flex;gap:4px;max-width:420px}
.sw{flex:1;height:26px;border-radius:5px;display:flex;align-items:center;justify-content:center}
.sw span{font-size:11px;font-weight:700;color:var(--bg)}
.ramp .sub{max-width:none}
.gray{filter:grayscale(1)}
footer{margin-top:22px;color:#98a2b0;font-size:12px}
"""


def render_html() -> str:
    dark, light = tokens.load_theme("dark"), tokens.load_theme("light")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ad2v visual tokens</title>
<style>{CSS}</style></head>
<body>{_defs([dark, light])}
<div class="page">
<div class="intro">
<h1>ad2v visual tokens v0.2</h1>
<p>Every glyph base shape (shape = node kind) under every link status (line style, fill and badge = status),
in the dark and light themes. Status never relies on color alone: the grayscale panel must still be readable.</p>
<p>Normative: status &rarr; line style / fill / decoration (docs/spec/visual-tokens-v0.2.md). Informative: the palettes.</p>
</div>
<div class="grid">
{_panel(dark)}
{_panel(light)}
{_panel(dark, "gray", "Dark theme, color removed (grayscale check)")}
</div>
<footer>Generated by ad2v {escape(__version__)} &middot; <code>ad2v preview-tokens</code> &middot; self-contained, no external assets.</footer>
</div></body></html>
"""
