# ADR-0067: Viewer packages are optional in a source install; required for a release build

- Status: accepted (P9)
- Context: the P8.1 push ran CI for the first time, and both runs failed within about 12 seconds.
  A fresh checkout has no `viewer/dist` or `viewer/app-dist`, because both are build outputs and
  ignored by git. `pyproject.toml` mapped the `ad2v._viewer` and `ad2v._app` packages onto those
  folders through `[tool.setuptools] package-dir`, so `pip install -e .` stopped with a setuptools
  error before a single test ran. Anyone cloning the repository hit the same failure.

## Decisions

1. **The setuptools package list moves to `setup.py`** (`PACKAGES`, `PACKAGE_DIR`,
   `PACKAGE_DATA`). `pyproject.toml` keeps the project metadata and dependencies, plus a comment
   that points to `setup.py`. setuptools reads both files; nothing else changes.
2. **The viewer packages are optional.** `ad2v._viewer`, `ad2v._viewer.assets` and `ad2v._app` are
   added only when their build folder exists. A source install without a viewer build works: the
   CLI, MCP agent tools and every non-viewer test run. `ad2v view` then says the viewer is not
   built, as before.
3. **A release build must include them.** With `AD2V_REQUIRE_VIEWER=1`, a missing folder is an
   error. `.github/workflows/release.yml` sets the variable on its build step, so a wheel without
   the viewer cannot be published by accident. The workflow is still disabled (`if: false`).
4. **Verified on a fresh copy before the P9 push.** A clean clone in a temporary folder ran
   `pip install -e .` with and without a viewer build, then
   `AD2V_REQUIRE_VIEWER=1 python -m build --wheel` (fails without the build, passes with it).

## Not done

- CI itself was not re-run before the P9 push. The next push is the check.
