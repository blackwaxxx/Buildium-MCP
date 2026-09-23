"""Build the Claude Desktop extension bundle (.mcpb).

An .mcpb is a zip with a manifest.json and the server. This one uses the ``uv``
server type: the bundle carries the package source, its dependency list and a
tiny entry script, and Claude Desktop provisions Python and the dependencies
itself with a copy of uv it manages. The user never installs Python, never
edits a config file, and enters their Buildium keys in a settings form that
Claude Desktop generates from ``user_config`` below.

Run from the project virtualenv, which must have the package importable
(the tool list is read from the live server):

    .venv/bin/python mcpb/build.py            # stage + pack -> dist/*.mcpb
    .venv/bin/python mcpb/build.py --stage    # stage only, into build/mcpb/

Packing needs Node (``npx @anthropic-ai/mcpb``, pinned by MCPB_CLI); staging
does not. A lockfile is written with ``uv lock`` when uv is on PATH so installs
are reproducible; without it, Claude Desktop's ``uv sync`` resolves at install
time instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build" / "mcpb"
DIST = ROOT / "dist"

sys.path.insert(0, str(ROOT / "src"))


# One settings form field per environment variable the server reads for
# configuration. The keys are what Claude Desktop shows the user; the ENV map
# below is what the server receives. test_mcpb.py asserts these agree with
# config.py, and that the defaults are the safe posture.
USER_CONFIG: dict[str, dict[str, Any]] = {
    "client_id": {
        "type": "string",
        "title": "Buildium Client ID",
        "description": (
            "From Buildium: Settings → Developer Tools → API keys. Sandbox and "
            "production are separate Buildium accounts with separate keys."
        ),
        "sensitive": True,
        "required": True,
    },
    "client_secret": {
        "type": "string",
        "title": "Buildium Client Secret",
        "description": "The secret paired with the Client ID above.",
        "sensitive": True,
        "required": True,
    },
    # The form has no dropdown, so the deployment mode is three toggles. The
    # bundle's server/main.py turns them into BUILDIUM_DEPLOYMENT_MODE and
    # BUILDIUM_BASE_URL; see its docstring for the mapping.
    "production": {
        "type": "boolean",
        "title": "Connect to production",
        "description": (
            "Off: the Buildium sandbox (a separate account with test data). "
            "On: your live Buildium account, read-only unless the next toggle "
            "is also on. Your API key must belong to the environment you pick."
        ),
        "default": False,
        "required": False,
    },
    "allow_writes": {
        "type": "boolean",
        "title": "Allow changes in production",
        "description": (
            "Off: in production, every request that could change a record is "
            "refused before it leaves your computer. On: Claude can create and "
            "edit live records. Leave off until you have used read-only for a "
            "while. Has no effect in the sandbox."
        ),
        "default": False,
        "required": False,
    },
    "allow_downloads": {
        "type": "boolean",
        "title": "Allow file downloads in production",
        "description": (
            "Buildium issues file downloads as a write-type request, so strict "
            "read-only cannot fetch a lease PDF. On: permit exactly Buildium's "
            "seven file-download endpoints and nothing else. Implied when "
            "changes are allowed. Has no effect in the sandbox."
        ),
        "default": False,
        "required": False,
    },
    "open_write_mode": {
        "type": "boolean",
        "title": "Allow changing records this session did not create",
        "description": (
            "Off (recommended for unattended use): new records must be named "
            "with the ZZ-MCPTEST- prefix, and only records created in this "
            "session can be edited or deleted. On: any record; deletes still "
            "need explicit confirmation."
        ),
        "default": False,
        "required": False,
    },
}

# What the server process receives. The two keys go straight through; the
# toggles arrive under BUILDIUM_MCPB_* names and server/main.py translates
# them, so the server itself still reads exactly one mode variable.
ENV: dict[str, str] = {
    "BUILDIUM_CLIENT_ID": "${user_config.client_id}",
    "BUILDIUM_CLIENT_SECRET": "${user_config.client_secret}",
    "BUILDIUM_MCPB_PRODUCTION": "${user_config.production}",
    "BUILDIUM_MCPB_ALLOW_WRITES": "${user_config.allow_writes}",
    "BUILDIUM_MCPB_ALLOW_DOWNLOADS": "${user_config.allow_downloads}",
    "BUILDIUM_MCPB_OPEN_WRITE_MODE": "${user_config.open_write_mode}",
}

ENTRY_POINT = "server/main.py"

# The packer that builds every released bundle. Pinned: `npx --yes` on a bare
# package name runs whatever was published last, so a new release of the
# packer — or a compromised one — would change what ships without a commit
# here. 2.1.2 built every bundle up to 0.1.2. Bump it deliberately.
MCPB_CLI = "@anthropic-ai/mcpb@2.1.2"


def project_meta() -> dict[str, Any]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def tool_list() -> list[dict[str, str]]:
    """Name and first paragraph of every tool, read from the live server."""
    from buildium_mcp import server

    tools = asyncio.run(server.mcp.list_tools())
    out = []
    for tool in sorted(tools, key=lambda t: t.name):
        first_paragraph = (tool.description or "").strip().split("\n\n", 1)[0]
        out.append({"name": tool.name, "description": " ".join(first_paragraph.split())})
    return out


def render_manifest() -> dict[str, Any]:
    meta = project_meta()
    urls = meta.get("urls", {})
    return {
        "manifest_version": "0.4",
        "name": meta["name"],
        "display_name": "Buildium",
        "version": meta["version"],
        "description": (
            "Ask Claude about your Buildium properties, leases, tenants, work "
            "orders and ledgers. Sandbox by default; production is read-only "
            "unless you say otherwise."
        ),
        "long_description": (
            "Exposes the whole Buildium Open API (462 operations) through 20 "
            "tools: search the API, describe an endpoint, read or call it, plus curated "
            "shortcuts for the common questions. Starts against the Buildium "
            "sandbox. Production access takes two deliberate settings, and the "
            "read-only production modes block every write at the network layer. "
            "Requires a Buildium Premium subscription with the Open API enabled."
        ),
        "author": {"name": meta["authors"][0]["name"]},
        "homepage": urls.get("Homepage"),
        "documentation": urls.get("Homepage"),
        "support": urls.get("Issues"),
        "repository": {"type": "git", "url": urls.get("Homepage")},
        "icon": "icon.png",
        "license": meta["license"] if isinstance(meta["license"], str) else "MIT",
        "keywords": list(meta.get("keywords", [])) + ["claude-desktop", "extension"],
        "server": {
            "type": "uv",
            "entry_point": ENTRY_POINT,
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--directory", "${__dirname}", ENTRY_POINT],
                "env": dict(ENV),
            },
        },
        "tools": tool_list(),
        "user_config": USER_CONFIG,
        "compatibility": {
            "platforms": ["darwin", "win32"],
            "runtimes": {"python": meta["requires-python"]},
        },
    }


def render_pyproject() -> str:
    """The bundle's own pyproject: dependencies only, nothing to build.

    ``package = false`` tells uv not to install this project into the
    environment, so no build backend is needed; server/main.py puts the
    bundled ``src`` on sys.path instead.
    """
    meta = project_meta()
    deps = "\n".join(f'    "{d}",' for d in meta["dependencies"])
    return (
        "# Generated by mcpb/build.py from the project's pyproject.toml.\n"
        "# Claude Desktop runs `uv sync` against this file at install time.\n"
        "[project]\n"
        f'name = "{meta["name"]}"\n'
        f'version = "{meta["version"]}"\n'
        f'description = "{meta["description"]}"\n'
        f'requires-python = "{meta["requires-python"]}"\n'
        f"dependencies = [\n{deps}\n]\n\n"
        "[tool.uv]\n"
        "package = false\n"
    )


def stage() -> Path:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    shutil.copytree(
        ROOT / "src" / "buildium_mcp",
        STAGE / "src" / "buildium_mcp",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (STAGE / "server").mkdir()
    shutil.copy(ROOT / "mcpb" / "main.py", STAGE / ENTRY_POINT)
    shutil.copy(ROOT / "mcpb" / "icon.png", STAGE / "icon.png")
    for name in ("LICENSE", "NOTICE"):
        shutil.copy(ROOT / name, STAGE / name)

    (STAGE / "pyproject.toml").write_text(render_pyproject())
    (STAGE / "manifest.json").write_text(json.dumps(render_manifest(), indent=2) + "\n")
    (STAGE / ".mcpbignore").write_text(".venv/\n__pycache__/\n*.pyc\n")

    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "lock", "--quiet"], cwd=STAGE, check=True)
    else:
        print("note: uv not on PATH; no uv.lock written (uv sync will resolve at install)")
    return STAGE


def pack() -> Path:
    npx = shutil.which("npx")
    if not npx:
        sys.exit("npx not found: packing needs Node. Staging succeeded; run `mcpb pack build/mcpb`.")
    DIST.mkdir(exist_ok=True)
    version = project_meta()["version"]
    out = DIST / f"buildium-mcp-{version}.mcpb"
    subprocess.run(
        [npx, "--yes", MCPB_CLI, "pack", str(STAGE), str(out)],
        check=True,
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--stage", action="store_true", help="stage only; do not pack")
    args = parser.parse_args()
    staged = stage()
    print(f"staged bundle in {staged.relative_to(ROOT)}")
    if args.stage:
        return
    out = pack()
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    os.chdir(ROOT)
    main()
