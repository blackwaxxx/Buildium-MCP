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
exactly one, and `test_config_reads_exactly_one_mode_env_var` parses `config.py`
to enforce that. If you think a second is needed, open an issue first.

**Widening the download carve-out by editing `DOWNLOAD_REQUEST_PATHS` alone.**
It is re-derived from the spec by a test. If Buildium adds a download endpoint,
the test tells you; if you are adding something that is not a download endpoint,
that is a different change and needs its own argument.

**Deriving a path from `__file__` depth.** `Path(__file__).parents[2]` is right
in a checkout and wrong in a wheel. Use `buildium_mcp.paths`.

**A new deployment mode without updating the enum-iteration tests.** They assert
exact sets precisely so that a new member cannot inherit permissions silently.

## Style

Match the surrounding code. Comments explain *why* — the non-obvious constraint,
the failure that motivated the shape — not what the line does.
