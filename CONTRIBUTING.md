# Contributing

## Setup

```bash
uv venv --python 3.11 && uv pip install -e ".[dev]"
pytest
```

The offline suite needs no credentials and no network. It is isolated from any
`.env` on your machine by `tests/conftest.py`, so a passing run means the code
passed — not that your sandbox happened to cooperate.

## Before you open a PR

```bash
pytest
```

Live checks, which need sandbox credentials and write to a real sandbox:

```bash
python tests/demo_readonly.py     # writes nothing; proves the guards hold
python tests/stdio_check.py       # full CRUD over real stdio JSON-RPC
```

## Things that will fail review

**Adding an environment variable that affects the deployment mode.** There is
exactly one, and `test_package_reads_exactly_one_deployment_mode_env_var` parses
every module in the package to enforce that. If you think a second is needed,
open an issue first.

**Widening the download carve-out by editing `DOWNLOAD_REQUEST_PATHS` alone.**
It is re-derived from the spec by a test. If Buildium adds a download endpoint,
the test tells you; if you are adding something that is not a download endpoint,
that is a different change and needs its own argument.

**Deriving a path from `__file__` depth.** `Path(__file__).parents[2]` is right
in a checkout and wrong in a wheel. Use `buildium_mcp.paths`.

**A new deployment mode without updating the enum-iteration tests.** They assert
exact sets precisely so that a new member cannot inherit permissions silently.

**A GitHub Action referenced by tag.** Every `uses:` names a full commit SHA with
its version in a comment, and `tests/test_mcpb.py` enforces it. A tag can be
moved by the action's owner; CI builds the released bundle and `release.yml`
can publish to PyPI. To update one, resolve the new tag to its commit and change
the SHA and the comment together.

## Releasing

1. Bump `version` in `pyproject.toml` and `__version__` in
   `src/buildium_mcp/__init__.py`, date the CHANGELOG entry, and merge.
2. Tag the merge commit (`git tag -a vX.Y.Z -m "buildium-mcp X.Y.Z"`) and push
   the tag.
3. Build the wheel and sdist from a clean export of the tag, so nothing
   untracked in your checkout can end up in them:
   `mkdir -p /tmp/rel && git archive --prefix=src/ vX.Y.Z | tar -x -C /tmp/rel && python -m build /tmp/rel/src`.
   Take the `.mcpb` from the `bundle` job of CI's run on the merge commit; it
   is built with uv, so it carries the lockfile.
4. Publish a GitHub release for the tag with those three files attached.
   `.github/workflows/release.yml` then uploads the wheel and sdist to PyPI,
   byte for byte, after checking they match the tag.

One-time PyPI setup, before the first release: at pypi.org, under Account →
Publishing, add a pending publisher with project `buildium-mcp`, owner
`blackwaxxx`, repository `Buildium-MCP`, workflow `release.yml` and environment
`pypi`. A pending publisher does not reserve the name, so publish soon after.
For a release that already exists, run the workflow by hand from the Actions
tab with its tag.

## Style

Match the surrounding code. Comments explain *why* — the non-obvious constraint,
the failure that motivated the shape — not what the line does.
