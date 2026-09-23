"""The Claude Desktop extension manifest must agree with the server.

mcpb/build.py generates manifest.json at build time. These tests pin the
things that would otherwise drift silently: the settings-form fields map onto
the environment variables the server actually reads, the defaults are the
safe posture, and the declared tool list is the real one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcpb import build  # noqa: E402
from mcpb import main as launcher  # noqa: E402
from buildium_mcp import config as cfg  # noqa: E402


@pytest.fixture(scope="module")
def manifest():
    return build.render_manifest()


def test_manifest_uses_the_uv_runtime(manifest):
    """uv is what lets Claude Desktop provision Python itself. A 'python'
    type would silently require the user to have Python installed."""
    assert manifest["manifest_version"] == "0.4"
    assert manifest["server"]["type"] == "uv"
    assert manifest["server"]["mcp_config"]["command"] == "uv"
    assert manifest["server"]["entry_point"] in manifest["server"]["mcp_config"]["args"]
    assert (ROOT / "mcpb" / "main.py").is_file()
    assert (ROOT / "mcpb" / "icon.png").is_file()


def test_every_env_var_the_form_sets_is_consumed(manifest):
    """The two keys go straight to the server; the toggles go to the launcher.

    Nothing else may appear: an env entry naming a variable neither of them
    reads would be a setting that silently does nothing.
    """
    env = manifest["server"]["mcp_config"]["env"]
    assert set(env) == {
        "BUILDIUM_CLIENT_ID", "BUILDIUM_CLIENT_SECRET",
        launcher.PRODUCTION, launcher.ALLOW_WRITES,
        launcher.ALLOW_DOWNLOADS, launcher.OPEN_WRITE_MODE,
    }
    for value in env.values():
        key = value.removeprefix("${user_config.").removesuffix("}")
        assert key in manifest["user_config"], f"{value} names no settings field"
    # and every settings field is wired to something
    wired = {v.removeprefix("${user_config.").removesuffix("}") for v in env.values()}
    assert wired == set(manifest["user_config"])


def test_mode_settings_are_toggles_not_free_text(manifest):
    """The form has no dropdown; typing 'production-readonly-files' is not easy."""
    for key in ("production", "allow_writes", "allow_downloads", "open_write_mode"):
        assert manifest["user_config"][key]["type"] == "boolean"
        assert manifest["user_config"][key]["default"] is False


def test_secrets_are_marked_sensitive_and_required(manifest):
    for key in ("client_id", "client_secret"):
        field = manifest["user_config"][key]
        assert field["sensitive"] is True
        assert field["required"] is True


def test_form_defaults_are_the_safe_posture():
    """Installing the extension and filling in only the two keys must leave
    the user exactly where `pip install` with no other variables leaves them."""
    out = launcher.translate({"BUILDIUM_CLIENT_ID": "x", "BUILDIUM_CLIENT_SECRET": "y"})
    assert cfg.parse_deployment_mode(out[cfg.MODE_ENV_VAR])[0] is cfg.DeploymentMode.SANDBOX
    assert out["BUILDIUM_BASE_URL"] == cfg.DEFAULT_BASE_URL
    assert out["BUILDIUM_WRITE_MODE"] == "fixtures"
    assert out["BUILDIUM_CLIENT_ID"] == "x"  # passthrough untouched


# -- the launcher's toggle translation -----------------------------------------
#
# The server still reads exactly one variable to choose its mode; the launcher
# sets it from the toggles. These pin the mapping, and that every combination
# the launcher can produce is one the server's own two-factor check accepts.

_T, _F = "true", "false"


@pytest.mark.parametrize("production,writes,downloads,mode,url", [
    (_F, _F, _F, "sandbox", cfg.DEFAULT_BASE_URL),
    (_F, _T, _T, "sandbox", cfg.DEFAULT_BASE_URL),      # writes/downloads mean nothing in sandbox
    (_T, _F, _F, "production-readonly", "https://api.buildium.com"),
    (_T, _F, _T, "production-readonly-files", "https://api.buildium.com"),
    (_T, _T, _F, "production-write", "https://api.buildium.com"),
    (_T, _T, _T, "production-write", "https://api.buildium.com"),
])
def test_toggles_map_to_exactly_one_mode(production, writes, downloads, mode, url):
    out = launcher.translate({
        launcher.PRODUCTION: production,
        launcher.ALLOW_WRITES: writes,
        launcher.ALLOW_DOWNLOADS: downloads,
    })
    assert out[cfg.MODE_ENV_VAR] == mode
    assert out["BUILDIUM_BASE_URL"] == url
    # the server would accept this pairing: mode permits the host
    host = url.removeprefix("https://")
    cfg._check_host(host, cfg.DeploymentMode(mode))  # must not raise
    # the toggles themselves never reach the server
    assert not any(k.startswith("BUILDIUM_MCPB_") for k in out)


def test_production_writes_need_two_switches():
    """One toggle reaches live data read-only; changing it takes a second."""
    read_only = launcher.translate({launcher.PRODUCTION: _T})
    assert not cfg.DeploymentMode(read_only[cfg.MODE_ENV_VAR]).writes_allowed
    writes_alone = launcher.translate({launcher.ALLOW_WRITES: _T})
    assert writes_alone[cfg.MODE_ENV_VAR] == "sandbox"


@pytest.mark.parametrize("raw", ["", " ", "no", "off", "0", "False", "FALSE", "maybe", None])
def test_anything_but_an_explicit_yes_is_off(raw):
    env = {launcher.PRODUCTION: raw} if raw is not None else {}
    assert launcher.translate(env)[cfg.MODE_ENV_VAR] == "sandbox"


@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on", " true "])
def test_explicit_yes_spellings_are_on(raw):
    assert launcher.translate({launcher.PRODUCTION: raw})[cfg.MODE_ENV_VAR] == "production-readonly"


def test_open_write_mode_toggle():
    assert launcher.translate({launcher.OPEN_WRITE_MODE: _T})["BUILDIUM_WRITE_MODE"] == "open"
    assert launcher.translate({})["BUILDIUM_WRITE_MODE"] == "fixtures"


def test_declared_tools_are_the_real_tools(manifest):
    import asyncio

    from buildium_mcp import server

    real = sorted(t.name for t in asyncio.run(server.mcp.list_tools()))
    assert [t["name"] for t in manifest["tools"]] == real
    assert all(t["description"] for t in manifest["tools"])


def test_version_has_one_source(manifest):
    import buildium_mcp

    assert manifest["version"] == build.project_meta()["version"] == buildium_mcp.__version__


def test_bundle_pyproject_carries_the_same_dependencies():
    import tomllib

    bundled = tomllib.loads(build.render_pyproject())
    assert bundled["project"]["dependencies"] == build.project_meta()["dependencies"]
    assert bundled["project"]["requires-python"] == build.project_meta()["requires-python"]
    assert bundled["tool"]["uv"]["package"] is False, "nothing to build; main.py sets sys.path"


def test_apply_rewrites_the_environment_without_losing_anything_else():
    """Regression: the launcher once cleared os.environ before reading it."""
    env = {
        "PATH": "/usr/bin", "HOME": "/h",
        "BUILDIUM_CLIENT_ID": "id", "BUILDIUM_CLIENT_SECRET": "sec",
        launcher.PRODUCTION: "true", launcher.ALLOW_DOWNLOADS: "true",
    }
    launcher.apply(env)
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/h"
    assert env["BUILDIUM_CLIENT_ID"] == "id" and env["BUILDIUM_CLIENT_SECRET"] == "sec"
    assert env[cfg.MODE_ENV_VAR] == "production-readonly-files"
    assert env["BUILDIUM_BASE_URL"] == "https://api.buildium.com"
    assert launcher.PRODUCTION not in env and launcher.ALLOW_DOWNLOADS not in env


def test_the_packer_is_pinned_to_an_exact_version():
    """`npx --yes @anthropic-ai/mcpb` runs whatever was published last, so a
    new or compromised packer would change what ships without a commit."""
    import re

    assert re.fullmatch(r"@anthropic-ai/mcpb@\d+\.\d+\.\d+", build.MCPB_CLI)
    source = (ROOT / "mcpb" / "build.py").read_text()
    assert '"@anthropic-ai/mcpb",' not in source, "an unpinned call is back"


def test_ci_workflows_default_to_a_read_only_token():
    for name in ("ci.yml", "release.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text()
        assert "\npermissions:\n  contents: read\n" in text, name


def test_allow_writes_does_not_promise_edits_it_cannot_make(manifest):
    """With the write-mode toggle off, fixtures mode refuses edits to existing
    records. The old text said "Claude can create and edit live records"."""
    form = manifest["user_config"]
    allow = form["allow_writes"]["description"]
    assert "edit live records" not in allow
    assert "ZZ-MCPTEST-" in allow and "both" in allow


def test_every_workflow_action_is_pinned_to_a_commit():
    """A tag like @v4 can be moved by the action's owner. CI builds the
    released .mcpb and release.yml publishes to PyPI, so neither may run
    whatever a tag points at today."""
    import re

    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in path.read_text().splitlines():
            if "uses:" not in line:
                continue
            assert re.search(r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", line), (
                f"{path.name}: {line.strip()} is not pinned to a full commit SHA "
                "with its version in a comment"
            )
