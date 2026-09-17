"""Read-only sandbox exploration, used to design evaluation questions.

Every answer in evals/buildium_eval.xml was derived from this output, so the
questions are grounded in real data rather than invented. Strictly GET-only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from buildium_mcp.client import BuildiumClient, BuildiumError  # noqa: E402
from buildium_mcp.config import load_config  # noqa: E402

COLLECTIONS = [
    ("/v1/rentals", {"limit": 100}),
    ("/v1/rentals/units", {"limit": 100}),
    ("/v1/leases", {"limit": 100}),
    ("/v1/leases/tenants", {"limit": 100}),
    ("/v1/rentals/owners", {"limit": 100}),
    ("/v1/glaccounts", {"limit": 200}),
    ("/v1/workorders", {"limit": 100}),
    ("/v1/vendors", {"limit": 100}),
    ("/v1/bankaccounts", {"limit": 100}),
    ("/v1/associations", {"limit": 100}),
    ("/v1/tasks", {"limit": 100}),
    ("/v1/rentals/appliances", {"limit": 100}),
]


async def main() -> None:
    config = load_config()
    client = BuildiumClient(config)
    out: dict[str, list] = {}
    try:
        for path, query in COLLECTIONS:
            try:
                resp = await client.request("GET", path, query=query)
                data = resp.data if isinstance(resp.data, list) else [resp.data]
                out[path] = data
                print(f"{path:32s} {len(data):4d} records")
            except BuildiumError as exc:
                print(f"{path:32s} ERROR {str(exc)[:70]}")
                out[path] = []
    finally:
        await client.aclose()

    dump = Path(__file__).resolve().parents[1] / "sandbox-snapshot.json"
    dump.write_text(json.dumps(out, indent=1, default=str))
    print(f"\nsnapshot -> {dump} ({dump.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
