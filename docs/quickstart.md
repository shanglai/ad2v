# ad2v quickstart: step by step on your own project

Every local command here was run against the `payments-recon` fixture, and
`tests/test_quickstart.py` runs them again on each test run. Commands are shown for Windows
PowerShell. Where the POSIX shell (macOS, Linux) differs, the variant follows. Every command
accepts `--help`.

---

## 0. Where things go

```
my-project/                  ← your repo, as-is (no code changes required)
├── src/…                    ← Python code (ad2v extracts Python only)
├── tests/…                  ← pytest tests (optional: named test_req_001_…)
├── specs/                   ← the SDD, inside the repo and versioned with the code
│   ├── openapi.yaml         ← endpoints
│   ├── features/*.feature   ← Gherkin scenarios
│   └── components.md        ← Markdown (ad2v convention, spec-kit, Kiro or your own)
├── ad2v.yaml                ← optional manifest (containers, pairing, LLM config)
└── .gitignore               ← add: .ad2v/

C:\ad2v-maps\my-project.ad2v ← the output file, outside the repo (or in a gitignored .ad2v/)
```

**Why the SDD goes inside the repo.** `ad2v history` reads the specs from *each commit*. If the
specs live outside the repo, ad2v can't see how they changed, and `stale` ("the spec changed
after the code") never fires.

**Why the `.ad2v` file stays out of git.** It stores code snippets and LLM outputs. Treat it like
the source code itself. `ad2v specs bootstrap` also keeps its cache in `<repo>/.ad2v/`, so add
`.ad2v/` to `.gitignore`.

**The repo as-is:** ad2v only reads the repo and never runs your code. Everything in steps 3 and
4 is optional; each item makes the map more accurate.

---

## 1. Install ad2v (once)

```powershell
cd C:\path\to\ad2v
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
cd viewer; npm ci; npm run build; npm run build:app; cd ..
ad2v --version
```

POSIX: `source .venv/bin/activate`, and `(cd viewer && npm ci && npm run build && npm run build:app)`.

Node is only needed to build the viewer and the MCP App. `ad2v` itself is pure Python.

---

## 2. Try the fixture first (5 min)

```powershell
cd viewer; npm run fixtures; cd ..
ad2v view viewer\tests\fixtures\demo.ad2v
```

In the browser:
1. **Zoom:** wheel to zoom, double-click to enter a box, `Esc` to go up, `/` to search.
2. **Status:** enter `api` and find the red dashed orphan and the risky loop in `matching.py`.
3. **AI drift:** click **Normative status** in the toolbar to switch to the effective status, and
   look at REQ-003's drift with the AI badge.
4. **Replay:** pick `POST /v1/reconciliations` in **Replay a workflow…**, then step through it
   and move the detail slider. **Dim** greys out everything but the step.
5. **History:** in the bottom epoch strip, select epoch 3 and press **Compare with parent**.

---

## 2b. Existing project? Start with `ad2v init`

On a repository that already has code and specs, let `ad2v init` look first. It reads files
only: it runs nothing, calls no model and writes nothing unless you pass `--write`.

```powershell
ad2v init --repo C:\path\to\my-project
```

It prints what it found:
- the spec folders, with a score and the files per format;
- the prose no preset reads;
- the spec id prefixes;
- one container per project manifest, with its language and whether ad2v can read it;
- the vendored folders it drops;
- SQL, infrastructure, and test results or a pytest configuration;
- the route prefixes it cannot resolve.

Then it prints a proposed `ad2v.yaml`. Save the proposal outside the repository while you try it:

```powershell
ad2v init --repo C:\path\to\my-project --write C:\ad2v-maps\my-project.yaml
```

Open that file and fill in any empty value: `pairing.path_constants: {"settings.API_PREFIX": ""}`
means your routers are mounted under a setting whose value ad2v will not guess (for example
`/api/v1`). An empty value is ignored, so the file works as written. Then:

```powershell
ad2v extract --repo C:\path\to\my-project --manifest C:\ad2v-maps\my-project.yaml --out C:\ad2v-maps\my-project.ad2v
ad2v init --repo C:\path\to\my-project --check C:\ad2v-maps\my-project.yaml   # later: what changed since
```

`--check` exits 1 and lists the differences:
- new or vanished spec folders and containers;
- excludes that match nothing;
- prefixes your tests use that are missing from the manifest;
- empty path constants.

`--format json` prints the findings for tools. TypeScript, Java and other languages without an
active extractor are shown as `not_evaluable`, not as missing (step 7, **Legend**).

---

## 3. Your SDD format

ad2v reads specs deterministically. Use what you already have, mix them freely, and let ad2v find
them: without `--spec` it uses `spec_root` from `ad2v.yaml`, otherwise the first of `specs/`,
`spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`, `docs/sdd/` that holds a spec, plus a root
`openapi.yaml`. `extract` prints the roots it used. Spanish and English are both read: EARS
(`Cuando …, el sistema deberá …`), Gherkin with `# language: es`, and the team formats below.

**OpenAPI** (`specs/openapi.yaml`): endpoints pair with FastAPI, Flask and Starlette routes by
method and path. `x-ad2v-refs: [REQ-001]` ties an endpoint to a requirement.

**Gherkin** (`specs/features/*.feature`): tag scenarios with `@REQ-001`.

**ad2v convention** (`specs/components.md`). No `ad2v.yaml` needed:

```markdown
## Component: Reconciliation API {#CMP-001}
- [REQ-001] When an operator starts a run, the system shall fetch all bank statements for the date.
- [REQ-002] If amounts differ by more than one cent, then the system shall mark the pair unmatched.
```

**spec-kit** (`specs/001-payments/spec.md`, as spec-kit writes it). Ids become
`001-payments:FR-001`. A test named `test_payments_fr_001_…` links to it. No `ad2v.yaml` needed:

```markdown
### Functional Requirements
- **FR-001**: System MUST record every refund with its reason.
- **FR-002**: System MUST reject refunds above the original amount.
```

**Kiro** (`.kiro/specs/order-export/requirements.md`). Ids become `ORDEREXPORT-1`, and each
acceptance criterion becomes `ORDEREXPORT-1.2`:

```markdown
### Requirement 1: Export orders
**User Story:** As an accountant, I want a CSV export, so that I can reconcile.
1. WHEN an export is requested THEN the Exporter SHALL write one row per order
```

```yaml
spec_ids:
  test_name_prefixes: [REQ, ORDEREXPORT]    # so test_orderexport_1_… links
```

**Your own Markdown** (custom regexes):

```markdown
## Invoices
REQ: BILL-1 - When an invoice is paid, the system shall send a receipt.
REQ: BILL-2 - The system shall keep invoices for seven years.
```

```yaml
spec_root: requirements
spec_markdown:
  - glob: "requirements/*.md"
    preset: custom
    component: '^## (?P<name>.+?)\s*$'
    requirement: '^REQ: (?P<id>[A-Za-z]+-[0-9]+) - (?P<text>.+?)\s*$'
```

**A requirements table** (the `table` preset, picked by shape; no `ad2v.yaml` needed). Headers
are matched in Spanish or English, ignoring case and accents. A `Componente` column pairs each
row with the container of that name. `RNF-…` ids (or a `Tipo` cell saying *No funcional*) are
non-functional: counted apart and badged NFR in the viewer.

```markdown
## Requerimientos funcionales
| ID | Título | Descripción | Prioridad | Componente |
|----|--------|-------------|-----------|------------|
| RF-001 | Iniciar conciliación | Cuando el operador inicia una corrida, el sistema deberá cargar los movimientos. | Alta | Backend |
```

**User stories** (the `stories` preset). Each criterion becomes `HU-001.1`, `HU-001.2`, …:

```markdown
## HU-001 Cargar un extracto
Como operador, quiero cargar el extracto del banco, para conciliarlo con el libro mayor.

Criterios de aceptación:
1. Dado un archivo CSV válido, cuando lo cargo, entonces veo la cantidad de movimientos.
```

```yaml
spec_ids:
  test_name_prefixes: [REQ, RF, HU]     # so test_rf_002_… links to RF-002 (ad2v init proposes this)
```

Requirements get a short title: a `Título` column, a story heading or `- [REQ-001] (Título) …`
wins. Otherwise ad2v derives one from the text. The map labels them `RF-001 · Iniciar
conciliación`.

**Free prose** (design notes, Word exports): bootstrap it. `--from` paths are relative to
`--repo`:

```powershell
ad2v specs bootstrap --repo C:\path\to\my-project --from docs --plan        # free: lists files, estimates the cost
ad2v specs bootstrap --repo C:\path\to\my-project --from docs --yes --max-cost-usd 0.20 --manifest C:\path\to\my-project\ad2v.yaml
ad2v specs review    --repo C:\path\to\my-project                           # overlap with existing specs, staleness
ad2v specs approve   --repo C:\path\to\my-project notes.md                  # moves it into specs/: now it counts
```

Proposals use `REQ-X…` ids so they never clash with yours. Nothing counts until you approve it.
The `--yes` run calls your model (step 8).

Details: [spec Markdown convention §6–8](spec/spec-markdown-convention.md).

---

## 4. Optional: make the links explicit (recommended)

Without these, ad2v still pairs by route and by name, but explicit links are more precise.

- **Annotations in code:** `# ad2v: REQ-001` on the line above a function, or a docstring line
  `ad2v: REQ-001`.
- **Test names:** `test_req_001_starts_run` counts as a linked test.
- **Test results:** these are what mark requirements **verified**: `pytest --junitxml=junit.xml`.
- **`ad2v.yaml`** at the repo root is read automatically (pass `--manifest` only if it lives
  elsewhere):

```yaml
containers:                 # otherwise inferred from pyproject.toml / Dockerfile dirs
  - {name: api,    paths: [src/api],    kind: service, replicas: 2}
  - {name: worker, paths: [src/worker], kind: worker}
pairing:
  components: {CMP-001: api}            # spec component → container/component
  path_prefix_map: {"/v1": ""}          # if the spec paths lack a mount prefix
  orphan_policy: auto                   # auto | strict | off
  path_constants: {"settings.API_V1_STR": "/api/v1"}   # FastAPI prefixes from settings (see below)
# rules_overlay: ad2v-rules.yaml        # custom risk rules / severity weights
```

**Route prefixes from settings.** If your routers are mounted under `settings.API_V1_STR` (or any
setting), ad2v can't know the value: those routes link as `needs_review` until you either map the
expression in `pairing.path_constants` (above), or set `pairing.resolve_settings_defaults: true` to
use the literal default in your pydantic `Settings` class (the links then carry a warning that the
environment may override it).

---

## 5. First extraction

```powershell
mkdir C:\ad2v-maps -Force
ad2v extract --repo C:\path\to\my-project --test-results C:\path\to\my-project\junit.xml --out C:\ad2v-maps\my-project.ad2v
```

POSIX: `mkdir -p ~/ad2v-maps` and `ad2v extract --repo ~/code/my-project --test-results ~/code/my-project/junit.xml --out ~/ad2v-maps/my-project.ad2v`.

Add `--spec <dir>` (repeatable) to override the spec discovery. Drop `--test-results` if you have
none. The summary shows the spec roots used, the ports, the risky behaviors, the status counts and
any unresolved spec references.

```powershell
ad2v status   C:\ad2v-maps\my-project.ad2v --status missing
ad2v status   C:\ad2v-maps\my-project.ad2v --status orphan
ad2v inspect  C:\ad2v-maps\my-project.ad2v --top-risk 10
ad2v validate C:\ad2v-maps\my-project.ad2v
```

**Sanity check.** Before trusting the map, read the top risks and the orphans, and ask yourself
"Is that true?"

---

## 6. Add history (the "what changed while I wasn't looking" view)

```powershell
ad2v history --repo C:\path\to\my-project --commits HEAD~20..HEAD --into C:\ad2v-maps\my-project.ad2v
ad2v log         C:\ad2v-maps\my-project.ad2v
ad2v diff        C:\ad2v-maps\my-project.ad2v --format md
ad2v materialize C:\ad2v-maps\my-project.ad2v --epochs last:5
```

- `--commits` is a git range. `HEAD~20..HEAD` needs at least 21 commits. Use `--commits HEAD`
  to take the whole history of a young repository.
- Specs are found in each commit as in step 5. In `history`, `--spec` and `--manifest` are
  *relative to the repo*, because they're read from each commit.
- `materialize` prepares epochs for browsing in the viewer.

After each new commit or agent session, append one epoch (it reports "no changes" when nothing
changed):

```powershell
ad2v extract --repo C:\path\to\my-project --into C:\ad2v-maps\my-project.ad2v
```

---

## 7. Look at it

```powershell
ad2v view C:\ad2v-maps\my-project.ad2v
```

This serves on 127.0.0.1 only and opens your browser (`--no-browser` prints the URL instead).
Nothing is uploaded.

**Chat with your own model about the map** (optional; costs money, see step 8 for `llm:`):

```powershell
ad2v view C:\ad2v-maps\my-project.ad2v --chat --manifest C:\path\to\my-project\ad2v.yaml --chat-budget-usd 0.25
```

The model runs in the `ad2v view` process with your credentials; the page gets a one-time token in
its URL. The panel shows the budget meter and an estimate before each question; answers cite map
nodes (click to fly there) and the map follows with **Follow** on. The chat can't change anything:
for that it gives you the CLI command. With `provider: fake` it works offline for a dry run.

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
  project: your-gcp-project
  location: global
  model: gemini-3.8-flash
  output_language: en        # or es-MX
  pricing: {input_per_mtok: 0.75, output_per_mtok: 3.75}   # check current Vertex pricing
  budget_usd: 1.00
  summaries: {scope: structural}
  tasks:                     # thinking per task (low cost ~60% less per call in P7)
    summarize: {thinking: low}
    narrate: {thinking: low}
```

**Always plan first, and read the USD estimate.** `plan` makes no calls:

```powershell
ad2v llm plan C:\ad2v-maps\my-project.ad2v --manifest C:\path\to\my-project\ad2v.yaml
```

With the model's default thinking, real output has run about **2× the static plan** (reasoning
tokens); with `thinking: low` it ran **below** the plan in P7. The plan re-calibrates after the first
call of a run.

**Then run within a hard cap:**

```powershell
ad2v llm run C:\ad2v-maps\my-project.ad2v --manifest C:\path\to\my-project\ad2v.yaml --tasks judge,suggest --max-cost-usd 0.50 --yes
```

Start with `judge,suggest`: they're cheap and only need specs. `summarize,narrate` scale with the
repo size, so run them later and on purpose. Every call is labeled `project=ad2v`.

**Review the suggestions.** A human confirms them, and the decision is written to `ad2v.yaml`:

```powershell
ad2v suggestions list   C:\ad2v-maps\my-project.ad2v --open
ad2v suggestions accept C:\ad2v-maps\my-project.ad2v <id> --manifest C:\path\to\my-project\ad2v.yaml
ad2v suggestions reject C:\ad2v-maps\my-project.ad2v <id> --manifest C:\path\to\my-project\ad2v.yaml
```

Then re-extract with `--into`, and accepted links become normative.

---

## 9. Use it from Claude Desktop (MCP + the map inside the chat)

Put your `.ad2v` files in one folder (e.g. `C:\ad2v-maps`). Then edit
`%APPDATA%\Claude\claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ad2v": {
      "command": "C:\\path\\to\\ad2v\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ad2v", "mcp", "--root", "C:\\ad2v-maps"]
    }
  }
}
```

POSIX: `"command": "/path/to/ad2v/.venv/bin/python"`.

The same server runs by hand as `ad2v mcp --root C:\ad2v-maps` (stdio; add `--http` for
Streamable HTTP on 127.0.0.1).

Restart Claude Desktop and try:
- "Using ad2v, give me an overview of my-project and show it on the map."
- "Which requirements are missing or drifting? Show me where."
- "Replay how <main endpoint> works, step by step."
- "What changed in the last epoch? Highlight it."

The server is read-only. It never runs the LLM and never edits files; for those actions it hands
you the CLI command. More hosts: [docs/mcp.md](mcp.md).

---

## 10. Limits

- **Code extraction is Python only.** Code in other languages (TypeScript, Java, Go, …) is listed
  but not read: it shows as `not_evaluable` (thin, dotted, hollow, "∅" badge; see **Legend** in the
  viewer). Add `// ad2v: REQ-001` comments there so the spec item still points at the right file.
- **Spec formats:** OpenAPI 3, Gherkin, the ad2v convention, spec-kit `spec.md`, Kiro
  `requirements.md`, custom regexes. Not yet parsed: Kiro `design.md`/`tasks.md`, spec-kit
  `plan.md`/`tasks.md`, requirement tables.
- **Route prefixes from settings** (`settings.API_V1_STR`) are unresolved unless mapped (step 4);
  those routes link as `needs_review` by their path tail.
- **`verified` needs a JUnit file.** Without one, the best status is `implemented`.
- **Judge accuracy** was measured on 11 labeled links. Treat the "AI" drift badges as leads, not
  verdicts.
