# ADR-0008: Tooling choices

- Status: accepted (P1)
- Decisions:
  - `uv` was not installed on the development machine, so the environment uses the prompt's fallback:
    `python -m venv` plus `pip install -e .[dev]`. `pyproject.toml` is PEP 621, so `uv sync` works
    unchanged.
  - **argparse** instead of Click or Typer for the CLI: one less dependency to license-check, and
    stable in the stdlib.
  - **hatchling** (MIT) is the build backend. `schema/` is force-included in the wheel as
    `ad2v/_schema`, and `ad2v.resources` also finds it in a source checkout.
  - Dependencies use compatible ranges, and the grammar is pinned exactly
    (`tree-sitter-python==0.25.0`) because the grammar version decides node types.
  - The CLI writes dumps as UTF-8 bytes with LF to `sys.stdout.buffer`, so `ad2v dump > x.jsonl` is
    byte-identical on Windows and POSIX.
