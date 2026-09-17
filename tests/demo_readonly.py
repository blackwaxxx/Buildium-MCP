"""Demonstrate that production-readonly blocks writes, against the live sandbox.

"Structurally impossible" is a strong claim, so this makes it checkable in ten
seconds rather than asking you to trust a unit test. It sets the deployment mode to
PRODUCTION_READONLY through BUILDIUM_DEPLOYMENT_MODE, points at the
sandbox, and then tries to write four different ways — including reaching past
BuildiumClient to the raw httpx client, which is what code trying to route
around the policy would do.

Nothing is written. That is the point.

    .venv/bin/python tests/demo_readonly.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from buildium_mcp import config as cfg  # noqa: E402

# Exactly what an operator does: set the one environment variable. Note the
# base URL is left alone — this still runs against the sandbox, because mode
# grants permission and never changes the target.
os.environ[cfg.MODE_ENV_VAR] = cfg.DeploymentMode.PRODUCTION_READONLY.value

from buildium_mcp.client import (  # noqa: E402
    BuildiumClient,
    BuildiumError,
    ReadOnlyViolation,
)
from buildium_mcp.guards import FixtureTracker, GuardViolation, check_write  # noqa: E402

PROBE = {"Name": "ZZ-MCPTEST-this-should-never-be-created"}


async def main() -> int:
    config = cfg.load_config()
    assert config.is_sandbox, f"refusing to demonstrate against {config.host}"

    print(f"deployment mode  {config.mode.value} (from {config.mode_source})")
    print(f"host             {config.host}")
    print(f"writes_allowed   {config.writes_allowed}")
    print(f"health reports   {config.environment}\n")

    client = BuildiumClient(config)
    tracker = FixtureTracker(config)
    failures: list[str] = []

    def result(layer: str, blocked: bool, detail: str = "") -> None:
        print(f"  [{'BLOCKED' if blocked else 'LEAKED '}] {layer}"
              + (f" — {detail[:70]}" if detail else ""))
        if not blocked:
            failures.append(layer)

    print("Attempting to write, four ways:\n")

    try:
        check_write("POST", "/v1/rentals/appliances", PROBE, tracker)
        result("guards.check_write", False)
    except GuardViolation as exc:
        result("guards.check_write", True, str(exc))

    try:
        await client.request("POST", "/v1/rentals/appliances", body=PROBE)
        result("BuildiumClient.request", False)
    except BuildiumError as exc:
        result("BuildiumClient.request", True, str(exc))

    # The bypass attempt: skip every check above and drive httpx directly.
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        try:
            await client._client.request(method, "/v1/rentals/appliances", json=PROBE)
            result(f"raw httpx {method}", False)
        except ReadOnlyViolation:
            result(f"raw httpx {method}", True, "stopped in the transport, no socket opened")

    print("\nConfirming this is read-only, not simply offline:\n")
    try:
        resp = await client.request("GET", "/v1/rentals", query={"limit": 1})
        print(f"  [ALLOWED] GET /v1/rentals — HTTP {resp.status}, "
              f"{len(resp.data)} record returned")
    except BuildiumError as exc:
        print(f"  [BROKEN ] GET /v1/rentals — {exc}")
        failures.append("GET was blocked, which it should not be")

    await client.aclose()

    print("\n" + "=" * 62)
    if failures:
        print(f"FAILED: {len(failures)} layer(s) did not behave — {failures}")
        return 1
    print("All write paths blocked; reads unaffected. Nothing was written.")

    # The narrower mode: downloads permitted, everything else still refused.
    print("\nSame server in production-readonly-files:\n")
    os.environ[cfg.MODE_ENV_VAR] = cfg.DeploymentMode.PRODUCTION_READONLY_FILES.value
    files_config = cfg.load_config()
    files_client = BuildiumClient(files_config)
    try:
        for method, path, label in (
            ("POST", "/v1/files/1/downloadrequest", "a file download"),
            ("POST", "/v1/vendors", "a vendor write"),
            ("PUT", "/v1/files/1/downloadrequest", "PUT on a download path"),
            ("POST", "/v1/leases/1/downloadrequest", "a download path that is not real"),
        ):
            permitted = cfg.request_permitted(files_config.mode, method, path)
            verdict = "[ALLOWED]" if permitted else "[BLOCKED]"
            print(f"  {verdict} {method} {path} — {label}")

        request = files_client._client.build_request(
            "POST", "https://evil.example.com/v1/files/1/downloadrequest"
        )
        try:
            await files_client._client.send(request)
            print("  [!!!]     a download path on a foreign host was NOT blocked")
            return 1
        except ReadOnlyViolation:
            print("  [BLOCKED] the same path aimed at evil.example.com")
    finally:
        await files_client.aclose()

    print("\n" + "=" * 62)
    print("Exactly seven endpoints are exempt, and only on Buildium's hosts.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
