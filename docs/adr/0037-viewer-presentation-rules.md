# ADR-0037: Viewer presentation rules

- Status: accepted (P5)
- Decisions:
  1. **Neutral bodies, status on the outline.** Glyph bodies are a neutral surface with a light
     (16%) status tint. The status is carried by the outline style and badges (tokens §2). Fully
     saturated bodies made large containers read as alarms.
  2. **Open containers recede.** An opened slab is drawn toward the background so its children
     read on top.
     - Its badges sit at its front-left corner, not in the middle of its children.
     - Modifier badges (retry, fan-out, …) are hidden on open glyphs, since the children carry
       them.
     - Empty roll-up bars are not drawn.
  3. **AI badge** on nodes whose effective status comes from an LLM judgment. The effective toggle
     shows how many nodes differ from normative.
  4. **Suggestions** get dotted connectors and a `?` badge. When one spec item has suggestions at
     several containment levels, only the highest-containment code node is drawn and the others
     are listed as "also at other levels".
  5. **Mentions.** `(n_…)` ids in LLM text become links when they are in `mentions`, and are
     stripped otherwise.
  6. **Camera.** Orthographic isometric, with no rotation. Clip planes and the minimum zoom scale
     with the map's extent. Dispatch (about 8,500 units wide) was clipped with fixed planes and a
     fixed minimum zoom.
  7. **Labels** are collision-culled (at most 400) and re-placed once the camera has been still
     for 150 ms.
