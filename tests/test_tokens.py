"""Visual tokens: WCAG contrast in both themes, status readable without color, preview page."""

import itertools
import re

import pytest

from ad2v import glyphs, ir, preview, tokens

NON_TEXT_MIN = 3.0  # WCAG 2.x 1.4.11 non-text contrast
TEXT_MIN = 4.5  # WCAG 2.x 1.4.3 normal text


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_status_strokes_meet_non_text_contrast(theme_name):
    t = tokens.load_theme(theme_name)
    for status in ir.NODE_STATUSES:
        stroke = tokens.status_color(t, status)["stroke"]
        for bg in (t["background"], t["surface"]):
            ratio = tokens.contrast(stroke, bg)
            assert ratio >= NON_TEXT_MIN, f"{theme_name}/{status}: {stroke} on {bg} = {ratio:.2f}"


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_text_tokens_meet_text_contrast(theme_name):
    t = tokens.load_theme(theme_name)
    for key in ("text", "text_muted"):
        for bg in (t["background"], t["surface"]):
            assert tokens.contrast(t[key], bg) >= TEXT_MIN, (theme_name, key, bg)
    b = t["badge"]
    assert tokens.contrast(b["warning_text"], b["warning"]) >= TEXT_MIN  # the "!" glyph is text


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_severity_ramp_and_edges_visible(theme_name):
    t = tokens.load_theme(theme_name)
    assert len(t["severity_ramp"]) == 5
    for c in [*t["severity_ramp"], t["edge"], t["badge"]["warning"]]:
        assert tokens.contrast(c, t["background"]) >= NON_TEXT_MIN, (theme_name, c)


def test_no_two_statuses_differ_by_color_alone():
    styles = tokens.STATUS_STYLES
    assert set(styles) == set(ir.NODE_STATUSES)
    for (a, sa), (b, sb) in itertools.combinations(styles.items(), 2):
        assert sa.signature != sb.signature, f"{a} and {b} differ by color only"


def test_normative_style_mapping_matches_spec():
    s = tokens.STATUS_STYLES
    assert (s["specified"].line, s["specified"].fill) == ("dotted", "tinted")
    assert (s["implemented"].line, s["implemented"].decoration) == ("solid", "none")
    assert (s["verified"].line, s["verified"].decoration) == ("solid", "emphasis")
    assert (s["drift"].line, s["drift"].decoration) == ("solid", "warning_badge")
    assert s["orphan"].line == "dashed"
    assert (s["missing"].line, s["missing"].fill) == ("dotted", "hollow")
    assert s["needs_review"].line == "dash_dot"
    for st in s.values():
        assert st.line in tokens.LINE_STYLES and st.fill in tokens.FILLS
        assert st.decoration in tokens.DECORATIONS and st.weight in tokens.WEIGHTS


def test_theme_emphasis_differs_by_theme():
    assert tokens.load_theme("dark")["emphasis"]["kind"] == "glow"
    assert tokens.load_theme("light")["emphasis"]["kind"] == "halo"
    with pytest.raises(ValueError):
        tokens.load_theme("sepia")


def test_contrast_math():
    assert tokens.contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert tokens.contrast("#777777", "#777777") == pytest.approx(1.0)
    with pytest.raises(ValueError):
        tokens.luminance("#fff")


def test_contrast_test_would_catch_a_bad_color(monkeypatch):
    bad = {"stroke": "#1A1F29", "fill": "#000000"}  # near-black on near-black
    assert tokens.contrast(bad["stroke"], tokens.load_theme("dark")["background"]) < NON_TEXT_MIN


def test_preview_is_self_contained_and_complete():
    html = preview.render_html()
    assert html.startswith("<!doctype html>")
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html)  # no external assets
    assert "<script" not in html
    for shape in glyphs.BASE_SHAPES:
        for status in ir.NODE_STATUSES:
            assert f'aria-label="{shape} / {status}"' in html
    assert html.count("Severity ramp") == 3  # dark, light, grayscale panels
    assert 'filter="url(#glow-dark)"' in html and "glow-light" not in html


def test_glyph_svg_encodes_status_without_color():
    t = tokens.load_theme("light")
    assert 'stroke-dasharray="1.5 4.5"' in preview.glyph_svg("cylinder", "specified", t)
    assert 'fill="none"' in preview.glyph_svg("cylinder", "missing", t)
    assert "<text" in preview.glyph_svg("cloud", "drift", t)
    assert "stroke-dasharray" not in preview.glyph_svg("hexagon", "implemented", t)
    assert preview.glyph_svg("ring", "verified", t).count("<path") == 2  # halo + outline


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_overlay_badges_and_diff_tokens(theme_name):
    """P5: AI / suggestion / diff badges: unique glyphs, visible colors, readable glyph text."""
    t = tokens.load_theme(theme_name)
    glyphs_ = [g for g, _, _ in tokens.OVERLAY_BADGES.values()]
    assert len(set(glyphs_)) == len(glyphs_)  # the glyph alone tells them apart
    for name, (_glyph, color, text) in tokens.OVERLAY_BADGES.items():
        c, tx = tokens.token(t, color), tokens.token(t, text)
        assert tokens.contrast(c, t["background"]) >= NON_TEXT_MIN, (theme_name, name, c)
        assert tokens.contrast(tx, c) >= TEXT_MIN, (theme_name, name, tx, c)
    for key in ("normative", "suggestion"):
        assert tokens.contrast(t["link"][key], t["background"]) >= NON_TEXT_MIN, (theme_name, key)
    assert 0.2 <= t["diff"]["ghost_opacity"] <= 0.6


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_edges_and_outlines_read_on_open_floors_p61(theme_name):
    """P6.1 (ADR-0051): the open-container floor is a bg-lerped body; edges and every status stroke
    stay >= 3:1 on it, and on their own closed body (the light-theme "none" outline failed in P5)."""
    t = tokens.load_theme(theme_name)
    floors = [tokens.body_color(t, s, True) for s in ir.NODE_STATUSES]
    for f in floors:
        assert tokens.contrast(t["edge"], f) >= NON_TEXT_MIN, (theme_name, "edge", f)
    for s in ir.NODE_STATUSES:
        stroke = tokens.status_color(t, s)["stroke"]
        assert tokens.contrast(stroke, tokens.body_color(t, s, False)) >= NON_TEXT_MIN, (theme_name, s)
        for f in floors:
            assert tokens.contrast(stroke, f) >= NON_TEXT_MIN, (theme_name, s, f)


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_dim_the_rest_is_opaque_and_the_step_still_reads_p61(theme_name):
    t = tokens.load_theme(theme_name)
    assert t["dim"]["factor"] == 0.7
    hi = t["replay"]["highlight"]
    for s in ir.NODE_STATUSES:
        for c in (tokens.body_color(t, s, False), tokens.body_color(t, s, True)):
            assert tokens.contrast(hi, c) >= NON_TEXT_MIN  # the step's own body and its container
            assert tokens.contrast(hi, tokens.dimmed(t, c)) >= NON_TEXT_MIN
        assert tokens.contrast(hi, tokens.dimmed(t, tokens.status_color(t, s)["stroke"])) >= NON_TEXT_MIN
    assert tokens.contrast(hi, tokens.dimmed(t, t["edge"])) >= NON_TEXT_MIN
    assert tokens.mix("#000000", "#FFFFFF", 0.0) == "#000000"
    assert tokens.mix("#000000", "#FFFFFF", 1.0) == "#FFFFFF"


@pytest.mark.parametrize("theme_name", tokens.THEMES)
def test_infra_status_strokes_meet_non_text_contrast(theme_name):
    """P10 (ADR-0078): the Architecture view styles infra statuses with these tokens (and a line style)."""
    t = tokens.load_theme(theme_name)
    assert set(t["infra"]) == set(ir.INFRA_STATUSES)
    for status, c in t["infra"].items():
        for bg in (t["background"], t["surface"], c["fill"]):
            ratio = tokens.contrast(c["stroke"], bg)
            assert ratio >= NON_TEXT_MIN, f"{theme_name}/{status}: {c['stroke']} on {bg} = {ratio:.2f}"
