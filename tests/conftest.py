"""Isolation for the offline unit suite.

``load_config`` searches upward from the working directory for a ``.env``. That
is the right behaviour for a developer running the server from a checkout, and
the wrong behaviour for a test suite: running ``pytest`` inside a checkout that
has real credentials would silently hand them to every test, and a test that
reaches the network is no longer a unit test — it is a slow, flaky, rate-limited
integration test that also depends on one particular Buildium account's data.

So the unit suite starts from a known-empty configuration. Tests that want
credentials set them explicitly via monkeypatch, which is also self-documenting.

The live scripts (coverage_matrix, stdio_check, demo_readonly) are standalone
``__main__`` programs and are unaffected by this file.
"""

from __future__ import annotations

import pytest

# Every variable that can influence configuration. Cleared before each test so
# a developer's shell cannot change a result.
_CONFIG_VARS = (
    "BUILDIUM_CLIENT_ID",
    "BUILDIUM_CLIENT_SECRET",
    "BUILDIUM_BASE_URL",
    "BUILDIUM_DEPLOYMENT_MODE",
    "BUILDIUM_WRITE_MODE",
    "BUILDIUM_FIXTURE_PREFIX",
    "BUILDIUM_SPEC_PATH",
    "BUILDIUM_ENV_FILE",
    "BUILDIUM_CONFIG_DIR",
    "BUILDIUM_STATE_DIR",
    "BUILDIUM_RUN_LOG",
    "BUILDIUM_ARTIFACT_LOG",
)


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    for name in _CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)

    # No .env from anywhere: not the checkout, not the user's config dir.
    from buildium_mcp import paths

    monkeypatch.setattr(paths, "env_file_candidates", lambda: [])

    # Logs go somewhere disposable rather than the real user state directory.
    monkeypatch.setenv("BUILDIUM_STATE_DIR", str(tmp_path / "state"))

    # Deferred startup memoizes both success and failure; without this a test
    # that configures a broken server would poison every test after it.
    from buildium_mcp import runtime

    runtime.reset()
    yield
    runtime.reset()
