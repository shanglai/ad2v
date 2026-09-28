# Status: P1 (format spec v0.1 + IR + deterministic extractor)

| Milestone | Scope | State | Commit |
|---|---|---|---|
| M1 | IR, SQLite schema, ids/hashing, store, canonical dump, format spec | done | `f0eb889` |
| M2 | Glyph grammar spec + `glyphs.py` | done | `ac9803c` |
| M3 | Python code extractor (tree-sitter) + plugin interface | done | `9586d56` |
| M4 | Spec extractors (Gherkin, OpenAPI, Markdown convention) | done | `485139a` |
| M5 | Static workflows + projection | done | `db94e08` |
| M6 | Fixture `payments-recon` + `expected.yaml` golden tests | done | `833a1fb` |
| M7 | CLI (`extract`, `dump`, `inspect`, `validate`), determinism/ID-stability tests, rules_hash, perf smoke, docs, REPORT.md | done | final commit |

Quality gates at the end of P1: 66 tests passing, ruff clean, 94% line coverage. The canonical
dump is identical across repeated runs, a CRLF+BOM copy, and a renamed checkout.
