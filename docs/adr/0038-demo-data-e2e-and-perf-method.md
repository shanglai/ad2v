# ADR-0038: Demo data, end-to-end screenshots, and how performance is measured

- Status: accepted (P5)
- Decisions:
  1. **Demo LLM rows come from the fake provider** (`ReplayOnly` with hand-written recordings):
     - the REQ-003 drift judgment;
     - two suggestions for CMP-001;
     - four summaries;
     - the narrations of `POST /v1/reconciliations`.

     P5 makes no LLM calls. The UI labels the provider "fake" in the header, the welcome card and
     each summary.
  2. **Screenshots.** One Playwright tour per theme, six shots each, 12 in total:
     - system view;
     - entered container;
     - risky loop;
     - replay at two detail levels, in one shot;
     - effective drift with the AI badge;
     - diff between epochs 2 and 3.

     The e2e runs on SwiftShader, so screenshots do not depend on the machine's GPU.
  3. **Performance** is measured separately, on the real GPU.
     - Setup: headless Chromium with ANGLE on Direct3D 11 (`--use-angle=d3d11 --enable-gpu`),
       through `ad2v view`, with 10 s of real wheel and drag input.
     - Frame times come from `requestAnimationFrame` in the page.
     - Headed Chromium could not be started from the agent's sandbox. Headless with a hardware
       ANGLE backend renders on the same GPU, and the WebGL renderer string is recorded.
