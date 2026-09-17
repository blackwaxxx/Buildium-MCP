"""Install the packed bundle the way Claude Desktop does, and talk MCP to it.

Claude Desktop unpacks a .mcpb into its own extensions directory, runs
``uv sync`` there, and launches the server with its managed uv binary using
the manifest's ``mcp_config.args``. This script does the same with the newest
``dist/*.mcpb``: unpacks it into a temporary directory *outside this
checkout* (so nothing here — least of all the repo's .env — can leak into the
test), syncs a fresh environment, then performs the MCP handshake, lists
tools, and calls buildium_health.

    .venv/bin/python mcpb/build.py && .venv/bin/python mcpb/smoke.py

With no BUILDIUM_* variables in the environment the server must still start
and health must explain what is missing; that is the state a user is in
between installing the extension and filling in the settings form. Pass
``--with-env`` to forward BUILDIUM_* variables from your shell and prove a
real read works through the bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def install(bundle: Path) -> Path:
    """Unpack like the host: a fresh directory that is not under the repo."""
    target = Path(tempfile.mkdtemp(prefix="mcpb-install-")) / bundle.stem
    with zipfile.ZipFile(bundle) as zf:
        zf.extractall(target)
    return target


class Stdio:
    def __init__(self, cmd: list[str], env: dict[str, str], cwd: Path):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("server exited:\n" + (self.proc.stderr.read() if self.proc.stderr else ""))
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == self._id:
                return resp

    def close(self) -> str:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)
        return self.proc.stderr.read() if self.proc.stderr else ""


def payload(resp: dict):
    result = resp.get("result") or {}
    if "structuredContent" in result:
        return result["structuredContent"]
    for block in result.get("content", []):
        if block.get("type") == "text":
            return json.loads(block["text"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-env", action="store_true",
                        help="forward BUILDIUM_* from the environment")
    parser.add_argument("--bundle", type=Path, default=None,
                        help="the .mcpb to test (default: newest in dist/)")
    args = parser.parse_args()

    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv not on PATH")
    bundle = args.bundle or max(DIST.glob("*.mcpb"), key=lambda p: p.stat().st_mtime, default=None)
    if bundle is None:
        sys.exit("no dist/*.mcpb; run mcpb/build.py first")
    STAGE = install(bundle)
    print(f"== installed {bundle.name} into {STAGE} ==")
    manifest = json.loads((STAGE / "manifest.json").read_text())
    mcp_config = manifest["server"]["mcp_config"]

    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BUILDIUM_") or args.with_env}
    # A fresh environment: the host does exactly this, from a fresh checkout.
    env.pop("VIRTUAL_ENV", None)
    env["UV_PROJECT_ENVIRONMENT"] = str(STAGE / ".venv")

    print("== uv sync (what Claude Desktop runs at install) ==")
    subprocess.run([uv, "sync", "--quiet"], cwd=STAGE, env=env, check=True)
    py = subprocess.run([uv, "run", "--directory", str(STAGE), "python", "-c",
                         "import sys; print(sys.executable, sys.version.split()[0])"],
                        cwd=STAGE, env=env, check=True, capture_output=True, text=True).stdout.strip()
    print("  interpreter:", py)

    cmd = [uv] + [a.replace("${__dirname}", str(STAGE)) for a in mcp_config["args"]]
    print("== launch (what Claude Desktop runs at start) ==")
    print(" ", " ".join(cmd))
    # cwd is the install directory, as in the host. `uv run --directory` would
    # make it that anyway; the point of installing outside the checkout is
    # that the server's upward .env search then finds nothing of ours.
    client = Stdio(cmd, env, cwd=STAGE)
    failures = []
    try:
        init = client.send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                          "clientInfo": {"name": "mcpb-smoke", "version": "0"}})
        client.send("notifications/initialized", {}, notify=True)
        name = (init.get("result", {}).get("serverInfo") or {}).get("name")
        print(f"  initialize -> serverInfo.name={name!r}")
        if name != "buildium_mcp":
            failures.append("initialize")

        tools = [t["name"] for t in client.send("tools/list", {}).get("result", {}).get("tools", [])]
        declared = [t["name"] for t in manifest["tools"]]
        print(f"  tools/list -> {len(tools)} tools; manifest declares {len(declared)}")
        if sorted(tools) != sorted(declared):
            failures.append("tool list differs from manifest")

        health = payload(client.send("tools/call", {"name": "buildium_health", "arguments": {}}))
        print(f"  buildium_health -> ok={health.get('ok')} mode={health.get('deployment_mode')} "
              f"stage={health.get('stage')} env_files_loaded={health.get('env_files_loaded')}")
        print(f"                     spec={health.get('spec')}")
        # resolve(): on macOS the temp dir is /var/..., a symlink to /private/var/...
        if not str(health.get("spec", "")).startswith(str(STAGE.resolve())):
            failures.append("spec not read from the bundle")
        if args.with_env:
            if health.get("ok") is not True:
                failures.append(f"health not ok with credentials: {health.get('error')}")
            rentals = payload(client.send("tools/call", {"name": "buildium_list_rentals",
                                                         "arguments": {"limit": 1, "fields": ["Id"]}}))
            print(f"  buildium_list_rentals -> ok={rentals.get('ok')} count={rentals.get('count')}")
            if rentals.get("ok") is not True:
                failures.append("live read failed")
        else:
            if health.get("ok") is not False or health.get("stage") != "credentials":
                failures.append("without credentials health must report the credentials stage")
            if not health.get("remedy"):
                failures.append("health carries no remedy")
    finally:
        stderr = client.close()
    banner_ok = "buildium-mcp" in stderr and "DEPLOYMENT MODE" in stderr
    print(f"  banner on stderr: {'yes' if banner_ok else 'NO'}")
    if not banner_ok:
        failures.append("banner missing")
    print("FAILURES: " + "; ".join(failures) if failures else "BUNDLE OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
