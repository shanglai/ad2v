# ADR-0050: The replay camera keeps every step on screen and readable

- Status: accepted (P6.1)
- Context: the user's question about the P5 demo: "when I replay a flow and there's an invisible
  element … why does it seem empty?" The P5 camera did not move with the replay, so a step
  could be off screen, or a few pixels wide.
- Decisions:
  1. `MapScene.frameStep(ids)` runs on every replay step, at every detail level, and for the App
     `path` intent:
     - **fit** when the step's screen box covers more than 80% of the viewport, or less than 90%
       of it is inside;
     - **zoom** toward the label LOD (40 px on the smaller side, `THRESHOLDS[1]`), capped so
       the parent container stays in view;
     - otherwise **pan** only, so small moves do not make the camera jump.
  2. **Ring.** A step still under 40 px (for example a port) gets a ring of at least 44 px
     around it, measured from the projected circle (16 samples), so it is visible at any zoom.
  3. **Deviation.** The prompt suggested re-framing when 30% of the step is off screen. That
     contradicts its own acceptance test (≥ 90% inside). We use 10%.
  4. Reduced motion makes the move instant. Otherwise it is the existing fly animation.
- Verification: `e2e/replay-camera.spec.ts`, POST /v1/reconciliations at levels 1 and 2, both
  themes: all 13 steps are 100% inside and 44–416 px on the smaller side.
