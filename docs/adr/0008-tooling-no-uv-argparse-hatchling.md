# ADR-0008: Tooling choices

- Status: accepted (P1). Amended during M7: build backend changed from hatchling to setuptools.
- Decisions:
  - `uv` was not installed on the development machine, so the environment uses the prompt's fallback:
    `python -m venv` plus `pip install -e .[dev]`. `pyproject.toml` is PEP 621, so `uv sync` works
    unchanged.
  - **argparse** instead of Click or Typer for the CLI: one less dependency to license-check, and
    stable in the stdlib.
  - **setuptools** is the build backend. hatchling was used first, but it depends on `pathspec`,
    which is **MPL-2.0**, and the no-copyleft rule covers build-time dependencies too. setuptools has
    no dependencies. `schema/` stays the canonical location. It ships in the wheel as the data package
    `ad2v._schema` (via `package-dir`), and `ad2v.resources` also finds it in a source checkout.
    Note for developers switching from an old checkout: remove any leftover
    `site-packages/ad2v/` directory from the hatchling editable install, which would shadow the
    package.
  - Dependencies use compatible ranges. The grammar is pinned exactly (`tree-sitter-python==0.25.0`)
    because the grammar version decides node types.
  - The CLI writes dumps as UTF-8 bytes with LF to `sys.stdout.buffer`, so `ad2v dump > x.jsonl` is
    byte-identical on Windows and POSIX.
