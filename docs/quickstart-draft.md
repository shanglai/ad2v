# ad2v quickstart (v0.6, P6.1 draft): step by step on your own project

This guide is written for Windows PowerShell. On macOS or Linux, swap the paths and the venv
activation. Any command here also accepts `--help` if a flag doesn't match your build.

---

## 0. Where things go

```
my-project/                  ← your repo, as-is (no code changes required)
├── src/…                    ← Python code (v0.6 extracts Python only)
├── tests/…                  ← pytest tests (optional: named test_req_001_…)
├── specs/                   ← the SDD, inside the repo and versioned with the code
│   ├── openapi.yaml         ← endpoints            (parsed deterministically)
│   ├── features/*.feature   ← Gherkin scenarios    (parsed deterministically)
│   └── components.md        ← Markdown convention  (parsed deterministically)
├── ad2v.yaml                ← optional manifest (containers, pairing, LLM config)
└── .gitignore               ← add: .ad2v/

C:\ad2v-maps\my-project.ad2v ← the output file, outside the repo (or in a gitignored .ad2v/)
```

**Why the SDD goes inside the repo.** `ad2v history` reads the specs from *each commit*. If the
specs live outside the repo, ad2v can't see how they changed, and `stale` ("the spec changed
after the code") never fires.

**Why the `.ad2v` file stays out of git.** It stores code snippets (the `source_blobs` table)
and the LLM outputs. Treat it like the source code itself: don't publish or share it casually.

**The repo as-is:** yes. ad2v only reads the repo and never runs your code. Everything in step 3
is optional, and each item makes the map more accurate.

---

## 1. Install ad2v (once)

```powershell
cd C:\Users\David\Documents\projects\agents\ad2v
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
cd viewer; npm ci; npm run build; npm run build:app; cd ..
ad2v --help
```

Node is only needed to build the viewer and the MCP App. `ad2v` itself is pure Python.

---

## 2. Try the fixture first (5 min)

```powershell
cd viewer; npm run fixtures; cd ..
ad2v view viewer\tests\fixtures\demo.ad2v
```

Explore in the browser:
1. **Zoom:** wheel to zoom and double-click to enter a box; `Esc` goes up and `/` searches.
2. **Status:** open `container:api` and find the red dashed orphan and the risky loop in
   `matching.py`.
3. **AI drift:** turn on the effective toggle and look at REQ-003's drift with the AI badge.
4. **Replay:** open a card, press ▶ on `POST /v1/reconciliations` and move the detail slider.
5. **History:** use the bottom scrubber to compare epoch 2 → 3.

If the demo file path differs, look in `viewer\tests\fixtures\`.

---

## 3. Prepare your project's SDD (the part that matters)

ad2v understands three spec formats deterministically. Use whichever you already have.

**a) OpenAPI:** `specs/openapi.yaml`. Endpoints are matched to FastAPI/Flask routes by method +
path. Tie an endpoint to a requirement with `x-ad2v-refs: [REQ-001]`.

**b) Gherkin:** `specs/features/*.feature`. Tag scenarios with `@REQ-001` to link them to
requirements.

**c) Markdown convention:** `specs/components.md`

```markdown
## Component: Reconciliation API {#CMP-001}

- [REQ-001] When an operator starts a run, the system shall fetch all bank statements for the date.
- [REQ-002] If an amount differs by more than one cent, then the system shall mark the pair unmatched.
```

Use the `CMP-xxx` and `REQ-xxx` IDs, one requirement per line, in "When…, the … shall…" form.

**d) spec-kit or Kiro, as they are** (P6.1). Keep spec-kit's `specs/001-feature/spec.md` or
Kiro's `.kiro/specs/<feature>/requirements.md` where the tools put them; ad2v recognizes them:
- spec-kit: `**FR-001**` and `**SC-001**` become `001-feature:FR-001`; user stories become scenarios.
  A test named `test_feature_fr_001_…` links to it.
- Kiro: `### Requirement 1` becomes `<FEATURE>-1` and each acceptance criterion `<FEATURE>-1.2`
  (the prefix is the folder name in capitals, for example `ORDEREXPORT`). Add the prefix to
  `spec_ids: test_name_prefixes:` in ad2v.yaml so `test_orderexport_1_…` links.

**e) Your own Markdown:** add a `spec_markdown` rule with `preset: custom` and a regex (see
[the convention, §6](spec/spec-markdown-convention.md)).

**Where ad2v looks.** Without `--spec`, ad2v uses `spec_root` from ad2v.yaml, otherwise it finds
`specs/`, `spec/`, `docs/specs/`, `.kiro/specs/` or a root `openapi.yaml` by itself. So
`my-project/` with `my-project/specs/` needs no flag. `extract` prints the roots it used.

**If your SDD is free prose** (design notes, Word docs exported to .md), bootstrap it:

```powershell
ad2v specs bootstrap --repo C:\path\to\my-project --from docs --plan        # free: lists files, estimates the cost
ad2v specs bootstrap --repo C:\path\to\my-project --from docs --yes --max-cost-usd 0.20 --manifest ad2v.yaml
ad2v specs review    --repo C:\path\to\my-project                           # overlap with existing specs, staleness
ad2v specs approve   --repo C:\path\to\my-project notes.md                  # moves it into specs/: now it counts
```

Proposals use `REQ-X…` ids so they never clash with yours. Nothing counts until you approve it.

---

## 4. Optional: make the links explicit (recommended)

Without these, ad2v still pairs by route and by name, but explicit links are more precise.

- **Annotations in code:** add `# ad2v: REQ-001` on the line above the function (or a docstring
  line `ad2v: REQ-001`).
- **Test names:** name tests like `test_req_001_starts_run`. They then count as linked tests.
- **Test results:** these are what can mark requirements as **verified**:

  ```powershell
  pytest --junitxml=junit.xml
  ```

- **`ad2v.yaml`** at the repo root, only if you need it:

```yaml
containers:                 # otherwise inferred from pyproject.toml / Dockerfile dirs
  - {name: api,    paths: [src/api],    kind: container, replicas: 2}
  - {name: worker, paths: [src/worker], kind: container}
pairing:
  components: {CMP-001: api}            # spec component → container/component
  path_prefix_map: {"/v1": ""}          # if the spec paths lack a mount prefix
  orphan_policy: auto                   # auto | strict | off
# rules_overlay: ad2v-rules.yaml        # custom risk rules / severity weights
```

---

## 5. First extraction (current state)

```powershell
mkdir C:\ad2v-maps -Force
ad2v extract --repo C:\path\to\my-project --spec C:\path\to\my-project\specs --manifest C:\path\to\my-project\ad2v.yaml --test-results C:\path\to\my-project\junit.xml --out C:\ad2v-maps\my-project.ad2v
```

Drop `--manifest` or `--test-results` if you don't have them. Then read the summary it prints:
status counts, the top 10 risky behaviors and unresolved refs.

```powershell
ad2v status  C:\ad2v-maps\my-project.ad2v --status missing
ad2v status  C:\ad2v-maps\my-project.ad2v --status orphan
ad2v inspect C:\ad2v-maps\my-project.ad2v --top-risk 10
ad2v validate C:\ad2v-maps\my-project.ad2v
```

**Sanity check.** Before trusting the map, read the 10 risks and 5 orphans, and ask yourself:
"Is that true?"

---

## 6. Add history (the "what changed while I wasn't looking" view)

```powershell
ad2v history --repo C:\path\to\my-project --spec specs --commits HEAD~20..HEAD --into C:\ad2v-maps\my-project.ad2v
ad2v log C:\ad2v-maps\my-project.ad2v
ad2v diff C:\ad2v-maps\my-project.ad2v --format md
ad2v materialize C:\ad2v-maps\my-project.ad2v --epochs last:5
```

`--spec` here is *relative to the repo*, because it's read from each commit. After each new
commit or agent session, append one epoch:

```powershell
ad2v extract --repo C:\path\to\my-project --spec C:\path\to\my-project\specs --into C:\ad2v-maps\my-project.ad2v
```

---

## 7. Look at it

```powershell
ad2v view C:\ad2v-maps\my-project.ad2v
```

This runs locally (127.0.0.1 only). Nothing is uploaded.

---

## 8. Optional: LLM layer (judge, suggestions, summaries, narrations). Costs money.

**Authenticate once.** No API key is needed:

```powershell
gcloud auth application-default login
```

**Add to `ad2v.yaml`:**

```yaml
llm:
  provider: vertex
  project: mapper-cat-3
  location: global
  model: gemini-3.8-flash
  output_language: en        # or es-MX
  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}   # check current Vertex pricing
  budget_usd: 1.00
  summaries: {scope: structural}
```

**Always plan first, and read the USD estimate:**

```powershell
ad2v llm plan C:\ad2v-maps\my-project.ad2v --manifest C:\path\to\my-project\ad2v.yaml
```

Real cost has run about **2× the plan**, because of Gemini's reasoning tokens.

**Then run within a hard cap:**

```powershell
ad2v llm run C:\ad2v-maps\my-project.ad2v --manifest C:\path\to\my-project\ad2v.yaml --tasks judge,suggest --max-cost-usd 0.50 --yes
```

Start with `judge,suggest`: they're cheap and only need specs. `summarize,narrate` scale with the
repo size (dispatch head-only was about $25), so run them later and on purpose. Every call is
labeled `project=ad2v`.

**Review the suggestions.** A human confirms them, and your decision is written to `ad2v.yaml`:

```powershell
ad2v suggestions list   C:\ad2v-maps\my-project.ad2v --open
ad2v suggestions accept C:\ad2v-maps\my-project.ad2v <id>
ad2v suggestions reject C:\ad2v-maps\my-project.ad2v <id>
```

Then re-extract with `--into`, and accepted links become normative.

---

## 9. Use it from Claude Desktop (MCP + the map inside the chat)

Put your `.ad2v` files in one folder (e.g. `C:\ad2v-maps`). Then edit
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ad2v": {
      "command": "C:\\Users\\David\\Documents\\projects\\agents\\ad2v\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ad2v", "mcp", "--root", "C:\\ad2v-maps"]
    }
  }
}
```

Restart Claude Desktop and try these prompts:
- "Using ad2v, give me an overview of my-project and show it on the map."
- "Which requirements are missing or drifting? Show me where."
- "Replay how <main endpoint> works, step by step."
- "What changed in the last epoch? Highlight it."

The server is read-only. It never runs the LLM and never edits files; for those actions it hands
you the CLI command.

---

## 10. Limits in v0.6

- **Code extraction is Python only.** Rust, TypeScript and other languages aren't mapped yet.
- **Spec formats:** OpenAPI 3, Gherkin, the Markdown/EARS convention, spec-kit `spec.md`, Kiro
  `requirements.md` and custom regexes. Not yet parsed: Kiro `design.md`/`tasks.md`, spec-kit
  `plan.md`/`tasks.md`, requirement tables. Prose needs `ad2v specs bootstrap`.
- **Route prefixes from settings** (`settings.API_V1_STR`) aren't resolved. Those routes link as
  `needs_review` by their path tail.
- **`verified` needs a JUnit file.** Without one, the best status is `implemented`.
- **Judge accuracy** was measured on only 11 labeled links. Treat the "AI" drift badges as leads
  to check, not verdicts.
- **Large repos** (5k+ nodes) render fast but look sparse or tangled at the top level. Viewer UX
  v2 is planned for P7.
