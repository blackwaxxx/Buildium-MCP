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


def test_every_env_var_the_form_sets_is_one_the_server_reads(manifest):
    env = manifest["server"]["mcp_config"]["env"]
    assert set(env) == {
        "BUILDIUM_CLIENT_ID", "BUILDIUM_CLIENT_SECRET", "BUILDIUM_BASE_URL",
        cfg.MODE_ENV_VAR, "BUILDIUM_WRITE_MODE",
    }
    for value in env.values():
        key = value.removeprefix("${user_config.").removesuffix("}")
        assert key in manifest["user_config"], f"{value} names no settings field"


def test_secrets_are_marked_sensitive_and_required(manifest):
    for key in ("client_id", "client_secret"):
        field = manifest["user_config"][key]
        assert field["sensitive"] is True
        assert field["required"] is True


def test_form_defaults_are_the_safe_posture(manifest):
    """Installing the extension and filling in only the two keys must leave
    the user exactly where `pip install` with no other variables leaves them."""
    uc = manifest["user_config"]
    assert cfg.parse_deployment_mode(uc["deployment_mode"]["default"])[0] is cfg.DeploymentMode.SANDBOX
    assert uc["base_url"]["default"] == cfg.DEFAULT_BASE_URL
    assert uc["write_mode"]["default"] == "fixtures"


def test_declared_tools_are_the_real_tools(manifest):
    import asyncio

    from buildium_mcp import server

    real = sorted(t.name for t in asyncio.run(server.mcp.list_tools()))
    assert [t["name"] for t in manifest["tools"]] == real
    assert all(t["description"] for t in manifest["tools"])


def test_version_matches_pyproject(manifest):
    assert manifest["version"] == build.project_meta()["version"]


def test_bundle_pyproject_carries_the_same_dependencies():
    import tomllib

    bundled = tomllib.loads(build.render_pyproject())
    assert bundled["project"]["dependencies"] == build.project_meta()["dependencies"]
    assert bundled["project"]["requires-python"] == build.project_meta()["requires-python"]
    assert bundled["tool"]["uv"]["package"] is False, "nothing to build; main.py sets sys.path"
