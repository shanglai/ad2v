# Dogfooding ad2v on two private repositories

A procedure to run ad2v on two private repositories that have specs, and to bring back results
that can be shared in the ad2v chat **without any code, names, paths or spec text from those
repositories**. It takes about an hour per repository, most of it manual checking.

Rules for this exercise:

- **No LLM.** The LLM layer (judge, summaries, narrations, the viewer chat, `specs bootstrap
  --yes`) is not part of dogfooding unless the owner approves a budget first. Every command below
  is deterministic and free. Do not pass `--chat`, and do not run `ad2v llm run`.
- **Nothing leaves your machine.** ad2v reads the repository and writes one `.ad2v` file. Keep the
  maps **outside** the private repositories (a `.ad2v` file contains code structure, names and spec
  text). Never commit or share a map, a screenshot or a status listing.
- **Share only** the results table (§5) and the findings in words (§6). `scripts/dogfood_counts.py`
  prints numbers only.

## 0. Set up once

Install ad2v from the checkout into its own virtual environment (not into a project's
environment):

```powershell
cd <repo-root>
python -m venv .venv-dogfood
.venv-dogfood\Scripts\pip install .
.venv-dogfood\Scripts\ad2v --version
```

(POSIX: `.venv-dogfood/bin/pip install .`.) Then, per private repository, set two variables
(PowerShell; POSIX `export REPO=…; export MAP=…`):

```powershell
$REPO = "C:\path\to\private-repo-a"
$MAP  = "C:\ad2v-maps\repo-a.ad2v"          # outside the repository
New-Item -ItemType Directory -Force C:\ad2v-maps | Out-Null
```

Call the repositories **Repo A** and **Repo B** in everything you share.

## 1. Start with `ad2v init`, then check how the specs are written

`ad2v init` (P9) reads the repository and proposes the manifest. It runs nothing, calls no model
and writes only with `--write`. Time it, and keep its report: it is the first finding.

```powershell
Measure-Command { .venv-dogfood\Scripts\ad2v init --repo $REPO | Out-Host }
.venv-dogfood\Scripts\ad2v init --repo $REPO --write C:\ad2v-maps\repo-a.ad2v.yaml
```

Open the written file. Fill in every empty `path_constants` value, and count those edits for the
results table. Remove anything that looks wrong and note why. The rest of this section is for
checking what `init` proposed.

ad2v finds specs in `--spec <dir>` (repeatable) > `spec_root` in `ad2v.yaml` > auto-detection
(`specs/`, `spec/`, `docs/specs/`, `.kiro/specs/`, `sdd/`, `docs/sdd/`, a root `openapi.*`).
`init` also finds folders with other names by content. For each format the repo uses, check the
shape (details: `docs/quickstart.md` §3):

| format | what ad2v reads | ids |
|---|---|---|
| Gherkin (`*.feature`) | features and scenarios; tag scenarios `@REQ-001` | `REQ-001` |
| ad2v Markdown convention | `## Component: Name {#CMP-001}` and `- [REQ-001] …` lines | `CMP-…`, `REQ-…` |
| spec-kit (`specs/<NNN-feature>/spec.md`) | `**FR-001**: System MUST …` | `<feature>:FR-001` |
| Kiro (`.kiro/specs/<name>/requirements.md`) | `### Requirement 1: …` + numbered EARS criteria | `NAME-1`, `NAME-1.2` |
| OpenAPI 3 | paths and methods | `GET /path` |
| requirements table (Spanish or English headers) | `| ID | Descripción | … |`, optional title / priority / type / component columns | as written (`RF-001`) |
| user stories | `HU-001` + "Como … quiero … para …" + acceptance criteria | `HU-001`, `HU-001.1` |
| your own Markdown | `spec_markdown` rules with `preset: custom` regexes | yours |

If anything needs configuration, create `ad2v.yaml` **outside** the repository (so you do not
modify it) and pass it with `--manifest`. A starting point:

```yaml
# C:\ad2v-maps\repo-a.ad2v.yaml  (keep it next to the map, not in the repo)
spec_root: [specs, .kiro/specs]          # only if auto-detection picks the wrong folders
spec_ids:
  test_name_prefixes: [REQ, FR, ORDEREXPORT]   # test names that count as links (Kiro prefixes)
pairing:
  orphan_policy: auto                    # auto | strict | off: try `strict` once and compare
  path_constants: {"settings.API_V1_STR": "/api/v1"}   # route prefixes that come from settings
  # resolve_settings_defaults: true      # alternative: read literal pydantic Settings defaults
  # path_prefix_map: {"/v1": ""}         # if the spec paths lack a mount prefix
# spec_markdown:                         # only for your own Markdown format
#   - {glob: "requirements/*.md", preset: custom, component: '^## (?P<name>.+?)\s*$',
#      requirement: '^REQ: (?P<id>[A-Za-z]+-[0-9]+) - (?P<text>.+?)\s*$'}
```

A manifest passed with `--manifest` resolves `spec_root` relative to the repository, and it must
stay inside it.

If the repository has test results, produce a JUnit file (for pytest: `pytest --junitxml
C:\ad2v-maps\repo-a-junit.xml`) so verified requirements can be counted.

## 2. Run ad2v and time it

**Infra (P10).** If the repository has Terraform, keep `infra_root` from the `init` proposal; that
reads the `.tf` statically. For deployment facts, produce one plan JSON per environment yourself
(`init` prints the command; it runs the providers and needs credentials), store it next to the map
(never in the repository), and add `--infra-plan prod=C:\ad2v-maps\repo-a-plan-prod.json` to the
extract below. Then look at the **Architecture** tab and `ad2v c4 $MAP --env prod`.

PowerShell (`Measure-Command { … }` prints the duration; POSIX: prefix with `time`):

```powershell
# 1. one epoch of the current checkout (add --test-results only if you produced one)
Measure-Command { .venv-dogfood\Scripts\ad2v extract --repo $REPO --manifest C:\ad2v-maps\repo-a.ad2v.yaml --test-results C:\ad2v-maps\repo-a-junit.xml --out $MAP | Out-Host }

# 2. aggregate counts for the results table (numbers only, safe to share)
.venv-dogfood\Scripts\python scripts\dogfood_counts.py $MAP

# 3. listings for the manual checks (do NOT share these)
.venv-dogfood\Scripts\ad2v status  $MAP --status drift
.venv-dogfood\Scripts\ad2v status  $MAP --status missing
.venv-dogfood\Scripts\ad2v status  $MAP --status orphan
.venv-dogfood\Scripts\ad2v status  $MAP --status needs_review
.venv-dogfood\Scripts\ad2v status  $MAP --status specified --side spec
.venv-dogfood\Scripts\ad2v status  $MAP --status not_evaluable
.venv-dogfood\Scripts\ad2v inspect $MAP --top-risk 10
.venv-dogfood\Scripts\ad2v inspect $MAP --kind http_route

# 4. history over the last N commits (N = 20 here; needs N+1 commits), into a separate map
Measure-Command { .venv-dogfood\Scripts\ad2v history --repo $REPO --commits HEAD~20..HEAD --into C:\ad2v-maps\repo-a-history.ad2v | Out-Host }
.venv-dogfood\Scripts\ad2v log  C:\ad2v-maps\repo-a-history.ad2v
.venv-dogfood\Scripts\ad2v diff C:\ad2v-maps\repo-a-history.ad2v --format md
.venv-dogfood\Scripts\ad2v materialize C:\ad2v-maps\repo-a-history.ad2v --epochs last:5

# 5. look at it (127.0.0.1 only; no chat)
.venv-dogfood\Scripts\ad2v view $MAP
```

Notes:

- In `history`, `--manifest`, `--spec` and `--test-results` are **relative to the repository**
  (they are read from each commit). An external manifest therefore cannot be used there; if you
  need configuration for history, skip the history row or note it as a gap.
- If `extract` prints `plug-in: …` lines, only the two built-ins should appear.
- `ad2v validate $MAP` should print `OK`.

## 3. What to capture

1. **Timings**: `extract` wall time, `history` wall time and number of commits, the viewer's first
   render (the HUD shows it), and whether the map stays fluid when zooming.
2. **Counts per status**: from `dogfood_counts.py` (`status_by_side`).
3. **False drift**: go through every `drift` row; for each, decide from the code and the spec
   whether the drift is real. Count real vs false.
4. **Missed pairings**: go through `missing` and `specified` spec items; count those that **are**
   implemented in the code (ad2v failed to pair them), and note why in words (no annotation, route
   path differs, name differs, unusual framework).
5. **False orphans**: go through `orphan` code nodes; count those that are in fact specified.
6. **Unresolved routes**: `http_routes_path_unresolved` from the counts, and in words what the
   prefixes come from (settings, a factory, a mount).
7. **Top-10 risk precision**: for each of the 10 rows of `inspect --top-risk 10`, is it a real
   risk worth a look (yes / no)? Precision = yes / 10.
8. **Extractor gaps**: things in the code that ad2v did not see at all: routes of an unsupported
   framework, jobs, CLIs, queues, datastores, or files skipped. Describe the *kind* of construct,
   never the code.
9. **Languages out of scope**: `unextracted_files_by_language` from the counts. Code in those
   languages is shown as `not_evaluable` (format v0.6): ad2v saw it but cannot judge it. Count the
   spec items that are `not_evaluable` and how many of them you would expect to be implemented.

## 4. Clean up

Delete the maps and the external manifests when done (`C:\ad2v-maps`), and `.venv-dogfood` if you
do not need it again. Nothing was written inside the private repositories.

## 5. Results table (fill one column per repository)

| item | Repo A | Repo B |
|---|---|---|
| language mix (e.g. "Python only", "Python + TS front end") | | |
| size: code files / code lines (`code_files`, `code_lines`) | | |
| spec formats used | | |
| `ad2v init` time (s) / proposal edits needed (count) / proposal entries removed (count) | | |
| configuration needed (none / spec_root / presets / path_constants / custom regexes) | | |
| `extract` time (s) | | |
| `history` time (s) / commits | | |
| viewer first render (s) / fluid? | | |
| nodes (total) | | |
| spec items: verified / implemented / not_evaluable / specified / missing / drift / needs_review / stale | | |
| non-functional requirements (count) / by status (`nonfunctional_requirements_by_status`) | | |
| code nodes: verified / implemented / not_evaluable / orphan / drift / needs_review | | |
| languages not read (files per language) | | |
| infra input (none / `infra_root` static / plan JSON per env) and its environments | | |
| infra resources by kind (`ad2v_overview` "Infra resources") / infra_other count | | |
| containers deployed / undeployed / ambiguous per env (and how many deploys needed `infra.deploys`) | | |
| env vars read / unwired per env; unwired checked / actually missing (false unwired) | | |
| infra_orphan resources checked / actually unused | | |
| Architecture tab: elements, relations, first render (s); does it match how the team draws the system? | | |
| drift rows checked / real / false | | |
| missing + specified checked / actually implemented (missed pairings) | | |
| orphans checked / actually specified (false orphans) | | |
| HTTP routes / with unresolved path | | |
| top-10 risk precision (x / 10) | | |
| unresolved spec references | | |
| extractor gaps found (count) | | |
| crashes or errors (count) | | |

## 6. Findings template (words only)

Copy this, fill it in, and paste it into the ad2v chat. Describe constructs generically
("a FastAPI router mounted from a factory with a prefix from settings"), never with real names,
paths, identifiers or spec text.

```text
Repo A / Repo B: <one-line description: domain-neutral, e.g. "internal API service, Python">

What worked:
- ...

False drift (n): why ad2v thought it drifted, generically:
- ...

Missed pairings (n): the patterns that defeated pairing:
- ...

False orphans (n): why they look unspecified to ad2v:
- ...

Unresolved routes (n): where the prefixes come from:
- ...

Top-10 risk: precision x/10; what the false positives had in common:
- ...

Extractor gaps: constructs ad2v did not see (kind of construct only):
- ...

Errors or crashes: the command and the error type (no paths):
- ...

Configuration I needed, and what was confusing:
- ...
```
