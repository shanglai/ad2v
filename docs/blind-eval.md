# Blind retrieval eval

The public retrieval eval sets (`fixtures/payments-recon/expected-questions.yaml`,
`fixtures/sdd-presets/expected-questions.yaml`, `fixtures/retrieval-eval/fastapi-template.yaml`) were
visible while the retrieval code was tuned (P6, P7), so their scores are optimistic. A **blind** set
is written by someone else, kept private, and only ever scored, never inspected by whoever changes
the retrieval code. The harness enforces that in code.

## Rules the harness enforces

- The set lives **outside the repository**, at the path in `AD2V_BLIND_EVAL`: one YAML file, or a
  directory whose `*.yaml` / `*.yml` files are all read. If you keep it inside the checkout, use
  `fixtures/retrieval-eval/blind/`, which is gitignored.
- `ad2v eval blind` prints and writes **aggregates only**: question counts, the SHA-256 of each blind
  file and of each map, and MRR, recall@5 and nDCG@5 with bootstrap 95% confidence intervals
  (percentile method, 2,000 resamples, seed 987654). It never prints a question, a gold id, a
  per-question row, a map label or a file name.
- Per-type aggregates appear only for types with at least 5 questions.
- Errors are sanitized: a YAML error gives a line number; invalid questions, unknown gold
  components and failures are counted, never quoted.
- A test (`tests/test_blind_eval.py`) plants marker strings in a temporary set and asserts that none
  of them reaches stdout, stderr or the `--out` file, including on error paths.

People working on ad2v (and coding agents) must not open, list or grep the blind location.

## File format

Copy `fixtures/retrieval-eval/blind-template.yaml` (its two questions are dummy examples on the
public fixture and are not part of any blind set):

```yaml
ad2v_blind_eval: 1
maps:
  repo-a: /path/to/repo-a.ad2v          # relative to the blind file, or absolute
questions:
  - {id: b001, map: repo-a, type: where, q: "where are invoices emailed?",
     gold: ["billing/mail.py::send_invoice"]}
  - {id: b002, map: repo-a, type: status, q: "which requirements are drifting?",
     gold: ["REQ-014"], tool: {name: status, status: drift}}
```

- `gold`: qualified names as `ad2v inspect` shows them (`kind:qname` when ambiguous), scored on the
  map's head epoch.
- `tool` (optional): when the question names a status or a diff, the tool a model would call.
- Aim for 30+ questions: with n = 30 the 95% interval on MRR is typically ±0.1.

## Running it

```bash
ad2v extract --repo /path/to/repo-a --out /path/to/repo-a.ad2v
```

```bash
AD2V_BLIND_EVAL=/path/to/blind.yaml ad2v eval blind
```

(PowerShell: `$env:AD2V_BLIND_EVAL = "C:\path\to\blind.yaml"; ad2v eval blind`.) Add `--json` for
machine-readable output, `--out results.json` to save it, `--locate-only` to score `ad2v_locate`
without the status/diff tools. The output is safe to paste into the ad2v chat.

Keep the SHA-256 lines: they prove that two runs scored the same, unchanged set.
