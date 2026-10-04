# Releasing ad2v

> **NOT FOR NOW.** Nothing is published until the owner decides (employer agreement first, then a
> fresh squashed public repository; see `docs/claude-context.md`). This page records how a release
> would work so that it is a checklist, not a project, when the time comes.

## Current state (P8)

- Version `0.7.0.dev0` (a pre-release; `.dev` versions are refused by the workflow).
- `pip install .` and the built wheel work in a clean virtual environment; the wheel contains the
  built viewer, `app.html`, the themes, the prompts and both rules files, and no fixtures, bench
  files, `.ad2v` files or `node_modules` (P8 report §M3).
- `.github/workflows/release.yml` exists and is disabled three ways: manual trigger only, a typed
  confirmation, and `if: false` on the publish job.

## One-time setup (when publishing is approved)

1. Make sure the public repository is the fresh squashed one and that the sanitization inventory
   (P8 M6) is clean for it.
2. On PyPI, create the project's **trusted publisher** (pending publisher if the name is new):
   owner/repository of the public repo, workflow `release.yml`, environment `pypi`.
3. In GitHub, create the environment **`pypi`** with *required reviewers* (the owner) and, optionally,
   a deployment branch rule (`main` only).
4. In `release.yml`, delete the `if: false` line of the `publish` job (one reviewed commit).
5. Optional dry run: point a copy of the workflow at TestPyPI
   (`repository-url: https://test.pypi.org/legacy/`) with its own trusted publisher.

## Each release

1. Set the version in `pyproject.toml`, `src/ad2v/__init__.py` and `viewer/package.json`
   (`viewer/src/app-main.ts` names it too); update the changelog section of the report.
2. Run the gates locally: `pytest`, `ruff`, `npm run lint && npm run typecheck && npm test`, both
   viewer builds (license gate), `ad2v extractor check` on the examples.
3. Merge; then run **Actions → release → Run workflow** with the exact version and the phrase
   `publish to PyPI`.
4. Approve the `pypi` environment when asked. The wheel and sdist are built from the commit the
   workflow ran on; nothing is signed with a long-lived token.
5. Tag the commit afterwards (`git tag vX.Y.Z`), if tags are wanted; the workflow does not tag.

## Tools

`build` and `twine` run in the workflow's own environment (or locally in a throwaway virtual
environment / pipx). They are never dependencies of ad2v (`docs/dependencies.md`, "Tools run
outside the tree").
