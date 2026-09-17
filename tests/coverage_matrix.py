"""Walk every operation in the Buildium spec and classify what we can prove.

This is the read half of the coverage matrix: it executes all 238 GET
operations against the sandbox for real. Writes are handled separately by
tests/coverage_writes.py, which is curated rather than exhaustive — see the
module docstring there for why.

The hard part is path parameters. 177 of the 238 GETs are templated
(`/v1/leases/{leaseId}/notes/{noteId}`), and an ID for one level only becomes
available once the level above has been read. So this runs in waves:

  wave 0   execute the 61 parameter-free collection GETs
  wave n   execute every templated GET whose parameters the pool can now fill,
           harvesting fresh IDs from each response
  stop     when a wave discovers no new IDs

Classification, per the five states asked for:

  verified      executed, 2xx
  needs-params  executed, rejected for missing or invalid *query* parameters
                — the endpoint works, the call needs more inputs than we could
                infer from the spec
  needs-setup   could not be attempted: no record of the required type exists
                in this sandbox, or the API key lacks the resource scope (403)
  write-skipped not applicable here; see coverage_writes.py
  broken        5xx, or a 4xx that does not fit the above

SAFETY: this module asserts method == GET before every request. It cannot
write even if edited carelessly.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from buildium_mcp.client import BuildiumClient, BuildiumError  # noqa: E402
from buildium_mcp.config import load_config  # noqa: E402
from buildium_mcp.spec import load_index  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "coverage-raw.json"

# Sandbox politeness. Buildium's documented ceiling is well above this; the
# point is to stay obviously clear of it rather than to go fast.
DELAY_S = 0.12

PARAM_RE = re.compile(r"\{(\w+)\}")

# Params that name a kind rather than a record. Buildium validates these
# against an enum, so guessing is not an option — these are the documented
# values, seeded by hand.
ENUM_SEEDS: dict[str, list[str]] = {
    "entityType": ["Rental", "Association"],
}

# Three endpoints demand a filter the spec does not mark required. Discovered
# by reading the 422 body, not by guessing. Recorded here rather than silently
# retried so the matrix can say WHY each needed special handling.
SPEC_UNDERSTATES: dict[str, dict[str, Any]] = {
    # "A valid FromPaidDate must be provided when the PaidStatus filter
    # returns paid bills" — and PaidStatus defaults to returning them.
    # ToPaidDate is required alongside it, also unmarked.
    "/v1/bills": {"frompaiddate": "@window_start", "topaiddate": "@window_end"},
    # "EntityType is required." / "EntityId is required." — neither appears in
    # the spec's parameter list for these two.
    "/v1/inventoryassets": {"entitytype": "Rental", "entityid": "@propertyId"},
    "/v1/inventorystorages": {"entitytype": "Rental", "entityid": "@propertyId"},
}

# Buildium caps every date-range filter at 365 days — "The time range must be
# less than or equal to 365 days" — and says so only in the 422 body, never in
# the spec. A trailing year is the widest window that is always accepted.
WINDOW_END = date.today()
WINDOW_START = WINDOW_END - timedelta(days=364)
EARLY_DATE = WINDOW_START.isoformat()
LATE_DATE = WINDOW_END.isoformat()


def _synthesize(name: str, schema: dict[str, Any], pool: "IdPool", path: str) -> Any:
    """Invent a plausible value for one required query parameter.

    Driven entirely by the parameter's declared schema, so this keeps working
    if Buildium adds endpoints. Dates are widened to a range that spans any
    plausible sandbox record rather than narrowed to a guess.
    """
    lower = name.lower()

    if schema.get("enum"):
        return schema["enum"][0]

    fmt = schema.get("format")
    if fmt in ("date", "date-time"):
        is_lower_bound = any(w in lower for w in ("from", "start", "after"))
        value = EARLY_DATE if is_lower_bound else LATE_DATE
        # A bare point-in-time param (readingdate, asofdate) wants a real day,
        # not a bound.
        return f"{value}T00:00:00Z" if fmt == "date-time" else value

    if schema.get("type") == "array":
        items = schema.get("items") or {}
        if items.get("enum"):
            return [items["enum"][0]]
        if items.get("type") == "integer":
            # 'glaccountids' -> the pool's 'glAccountId'. Matched
            # case-insensitively because query params are lowercase and path
            # params are camelCase.
            singular = lower[:-1] if lower.endswith("s") else lower
            found = pool.get_ci(singular, path)
            return [found] if found is not None else None
        return None

    if schema.get("type") in ("integer", "number"):
        return pool.get_ci(lower, path)

    return None


def camel_to_param(field: str) -> str:
    """'PropertyId' -> 'propertyId'. Buildium is consistent enough that this
    single rule connects most response fields to the path params that want
    them."""
    return field[0].lower() + field[1:]


def namespace_of(path: str) -> str:
    """Which family of IDs a path belongs to.

    Buildium reuses parameter names across unrelated ID spaces: a tenantId from
    /v1/associations/tenants is not a tenantId that /v1/leases/tenants will
    recognise, and feeding one to the other produces a 404 that looks like a
    broken endpoint but is really a bookkeeping error on our side. Keying the
    pool by the second path segment keeps the spaces apart.
    """
    parts = [seg for seg in path.strip("/").split("/") if seg]
    if parts and parts[0] == "v1":
        parts = parts[1:]
    return parts[0] if parts else "*"


class IdPool:
    """Every record ID seen so far, keyed by (namespace, path parameter).

    Lookups prefer a value harvested from the same namespace as the path being
    filled and fall back to any namespace, so a parameter that only ever
    appears in one place still resolves.
    """

    MAX_PER_KEY = 3

    def __init__(self) -> None:
        self.pool: dict[tuple[str, str], list[Any]] = defaultdict(list)
        self.sources: dict[str, str] = {}
        # Exact concrete paths proven to exist, keyed by the spec template they
        # satisfy. A child ID is only meaningful under the parent it came from
        # — note 17707 belongs to one association and 404s under every lease —
        # so the parent and child are recorded together as one path rather than
        # reassembled from two independent pools.
        self.known_paths: dict[str, list[str]] = defaultdict(list)
        for name, values in ENUM_SEEDS.items():
            self.pool[("*", name)] = list(values)
            self.sources[f"*:{name}"] = "seeded (enum)"

    def add(self, param: str, value: Any, source: str) -> bool:
        if value is None or value == 0:
            return False
        ns = namespace_of(source.split()[-1] if " " in source else source)
        bucket = self.pool[(ns, param)]
        if value in bucket or len(bucket) >= self.MAX_PER_KEY:
            return False
        bucket.append(value)
        self.sources.setdefault(f"{ns}:{param}", source)
        return True

    def candidates(self, param: str, target_path: str) -> list[Any]:
        """Values to try for `param`, same-namespace first."""
        ns = namespace_of(target_path)
        out: list[Any] = []
        for key in ((ns, param), ("*", param)):
            for value in self.pool.get(key, []):
                if value not in out:
                    out.append(value)
        if not out:  # any namespace, as a last resort
            for (_ns, name), bucket in self.pool.items():
                if name == param:
                    for value in bucket:
                        if value not in out:
                            out.append(value)
        return out

    def get(self, param: str, target_path: str = "") -> Any:
        found = self.candidates(param, target_path)
        return found[0] if found else None

    def get_ci(self, param: str, target_path: str = "") -> Any:
        """Case-insensitive lookup: query params are lowercase ('glaccountids')
        while path params are camelCase ('glAccountId')."""
        target = param.lower()
        for (_ns, name) in list(self.pool):
            if name.lower() == target:
                found = self.get(name, target_path)
                if found is not None:
                    return found
        return None

    def can_fill(self, path: str) -> bool:
        return all(self.candidates(p, path) for p in PARAM_RE.findall(path))

    def fill(self, path: str, variant: int = 0) -> str:
        """Substitute real IDs. `variant` picks an alternative candidate, used
        to give a 404 exactly one second chance before it is believed."""

        def sub(m: re.Match[str]) -> str:
            found = self.candidates(m.group(1), path)
            return str(found[min(variant, len(found) - 1)]) if found else m.group(0)

        return PARAM_RE.sub(sub, path)

    def variants(self, path: str) -> int:
        """How many distinct concrete paths this template can produce."""
        return max(
            (len(self.candidates(p, path)) for p in PARAM_RE.findall(path)),
            default=1,
        )

    def learn_path(self, spec_item_path: str, concrete: str) -> None:
        bucket = self.known_paths[spec_item_path]
        if concrete not in bucket and len(bucket) < self.MAX_PER_KEY:
            bucket.append(concrete)

    def known(self, spec_item_path: str, variant: int = 0) -> str | None:
        bucket = self.known_paths.get(spec_item_path)
        if not bucket:
            return None
        return bucket[min(variant, len(bucket) - 1)]

    def snapshot(self) -> dict[str, list[Any]]:
        return {f"{ns}:{name}": v for (ns, name), v in sorted(self.pool.items())}


def harvest(pool: IdPool, spec_path: str, concrete_path: str, data: Any, index) -> int:
    """Pull IDs out of a response into the pool.

    Two sources. First, the collection's own children: a GET on
    '/v1/leases/{leaseId}/notes' returns objects whose 'Id' is the noteId that
    '/v1/leases/{leaseId}/notes/{noteId}' is asking for, so the parameter name
    is read off the sibling item endpoint rather than guessed. Second, any
    'SomethingId' field anywhere in the record, which is how propertyId and
    unitId reach paths that never list them.
    """
    found = 0
    records = data if isinstance(data, list) else [data]

    # What does this collection's item endpoint call its ID?
    own_param: str | None = None
    for ep in index.endpoints:
        if ep.method != "get":
            continue
        if ep.path.startswith(spec_path.rstrip("/") + "/{") and \
                ep.path.count("/") == spec_path.count("/") + 1:
            m = PARAM_RE.search(ep.path.rsplit("/", 1)[-1])
            if m:
                own_param = m.group(1)
                break

    def walk(obj: Any, depth: int = 0) -> None:
        nonlocal found
        if depth > 3:
            return
        if isinstance(obj, list):
            for item in obj[:5]:
                walk(item, depth + 1)
            return
        if not isinstance(obj, dict):
            return
        for key, value in obj.items():
            if key == "Id" and depth == 0 and own_param:
                # Record the exact child path, not just the bare ID.
                pool.learn_path(
                    f"{spec_path.rstrip('/')}/{{{own_param}}}",
                    f"{concrete_path.rstrip('/')}/{value}",
                )
                if pool.add(own_param, value, spec_path):
                    found += 1
            elif key.endswith("Id") and key != "Id" and isinstance(value, (int, str)):
                if pool.add(camel_to_param(key), value, spec_path):
                    found += 1
            elif isinstance(value, (dict, list)):
                walk(value, depth + 1)

    for rec in records[:5]:
        walk(rec)
    return found


def query_for(endpoint, index, pool: IdPool) -> tuple[dict[str, Any], list[str]]:
    """Build the query string for one endpoint from its declared parameters.

    Returns the query plus the names of any required parameter this could not
    fill, so an endpoint that fails for a reason we already know about gets
    reported as such rather than as a mystery.
    """
    query: dict[str, Any] = {"limit": 5}
    unfilled: list[str] = []

    detail = index.describe(endpoint.method, endpoint.path) or {}
    for param in detail.get("parameters", []):
        if param.get("in") != "query" or not param.get("required"):
            continue
        name = param.get("name")
        value = _synthesize(name, param.get("schema") or {}, pool, endpoint.path)
        if value is None:
            unfilled.append(name)
        else:
            query[name] = value

    for name, value in SPEC_UNDERSTATES.get(endpoint.path, {}).items():
        if isinstance(value, str) and value.startswith("@"):
            token = value[1:]
            resolved = {"window_start": EARLY_DATE, "window_end": LATE_DATE}.get(
                token, pool.get(token, endpoint.path)
            )
            if resolved is None:
                unfilled.append(name)
                continue
            value = resolved
        query[name] = value

    return query, unfilled


def classify(status: int | None, message: str) -> tuple[str, str]:
    """Map an outcome onto the five states, with a reason worth reading."""
    low = message.lower()
    if status == 403:
        return "needs-setup", "API key lacks the resource scope for this endpoint (403)"
    if status == 404:
        return "needs-setup", "no record of this type exists in the sandbox (404)"
    if status in (400, 422):
        return "needs-params", f"rejected for missing or invalid parameters: {message[:220]}"
    if status is not None and status >= 500:
        return "broken", f"upstream {status}: {message[:220]}"
    if "network error" in low:
        return "broken", f"transport failure: {message[:220]}"
    return "broken", f"HTTP {status}: {message[:220]}"


async def attempt(
    client: BuildiumClient, method: str, concrete: str, query: dict[str, Any]
) -> tuple[str, str, int | None, Any]:
    assert method.upper() == "GET", "coverage_matrix.py is read-only by construction"
    try:
        resp = await client.request("GET", concrete, query=query, max_retries=1)
    except BuildiumError as exc:
        return (*classify(exc.status, str(exc)), exc.status, None)
    return "verified", f"HTTP {resp.status}", resp.status, resp.data


async def main() -> None:
    config = load_config()
    assert config.is_sandbox, f"refusing to run coverage against {config.host}"
    index = load_index(config.spec_path)
    client = BuildiumClient(config)

    gets = sorted(
        (e for e in index.endpoints if e.method == "get"), key=lambda e: e.path
    )
    pool = IdPool()
    results: dict[str, dict[str, Any]] = {}
    started = time.monotonic()

    print(f"{len(gets)} GET operations to walk. Sandbox: {config.host}\n")

    async def run_one(ep) -> bool:
        """Execute one endpoint. Returns True if it taught us a new ID."""
        query, unfilled = query_for(ep, index, pool)
        # A path we have already seen returned by its parent collection beats
        # anything reassembled from the ID pool.
        concrete = pool.known(ep.path) or pool.fill(ep.path)
        state, reason, status, data = await attempt(client, "GET", concrete, query)

        # Two bounded second chances, never more:
        #   a 404 may mean we guessed the wrong ID — try one alternative;
        #   an empty child collection may mean we picked a childless parent —
        #   try up to two other parents before calling the endpoint unproven.
        attempts_left = 2
        variant = 0
        while attempts_left > 0:
            retry = None
            if status == 404:
                variant += 1
                candidate = pool.known(ep.path, variant) or pool.fill(ep.path, variant)
                retry = candidate if candidate != concrete else None
            elif (
                state == "verified"
                and not data
                and "{" in ep.path
                and pool.variants(ep.path) > variant + 1
            ):
                variant += 1
                candidate = pool.fill(ep.path, variant)
                retry = candidate if candidate != concrete else None
            if retry is None:
                break
            attempts_left -= 1
            await asyncio.sleep(DELAY_S)
            s2, r2, st2, d2 = await attempt(client, "GET", retry, query)
            if s2 == "verified" and (d2 or status == 404):
                concrete, state, reason, status, data = retry, s2, r2, st2, d2
                break
            if status == 404 and s2 != "verified":
                concrete = retry  # report the last thing we actually tried

        if state == "needs-params" and unfilled:
            reason = (
                f"required parameter(s) {', '.join(unfilled)} could not be "
                f"supplied from sandbox data. Server said: {reason[:160]}"
            )

        results[ep.key] = {
            "method": "GET",
            "path": ep.path,
            "concrete_path": concrete,
            "operation_id": ep.operation_id,
            "tags": list(ep.tags),
            "summary": ep.summary,
            "state": state,
            "reason": reason,
            "status": status,
            "query": {k: v for k, v in query.items() if k != "limit"} or None,
            "unfilled_required": unfilled or None,
            "record_count": len(data) if isinstance(data, list) else (1 if data else 0),
        }
        await asyncio.sleep(DELAY_S)
        if state == "verified" and data is not None:
            return harvest(pool, ep.path, concrete, data, index) > 0
        return False

    wave = 0
    while True:
        pending = [e for e in gets if e.key not in results]
        ready = [e for e in pending if pool.can_fill(e.path)]
        if not ready:
            break
        wave += 1
        print(f"wave {wave}: {len(ready)} executable, {len(pending) - len(ready)} still blocked")
        learned = False
        for ep in ready:
            if await run_one(ep):
                learned = True
        if not learned and not [e for e in gets if e.key not in results and pool.can_fill(e.path)]:
            break

    # Anything still unreached has a path parameter the sandbox never produced.
    for ep in gets:
        if ep.key in results:
            continue
        missing = [p for p in PARAM_RE.findall(ep.path)
                   if not pool.candidates(p, ep.path)]
        results[ep.key] = {
            "method": "GET",
            "path": ep.path,
            "concrete_path": ep.path,
            "operation_id": ep.operation_id,
            "tags": list(ep.tags),
            "summary": ep.summary,
            "state": "needs-setup",
            "reason": (
                "not attempted: the sandbox contains no record supplying "
                f"{', '.join(missing)}. Creating one is a prerequisite."
            ),
            "status": None,
            "query": None,
            "record_count": 0,
        }

    elapsed = round(time.monotonic() - started, 1)
    await client.aclose()

    counts: dict[str, int] = defaultdict(int)
    for row in results.values():
        counts[row["state"]] += 1

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": config.host,
        "elapsed_s": elapsed,
        "read_results": results,
        "id_pool": pool.snapshot(),
        "id_sources": pool.sources,
    }
    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    existing.update(payload)
    OUT.write_text(json.dumps(existing, indent=1, default=str))

    print(f"\n{'=' * 60}\n{len(results)} GET operations in {elapsed}s")
    for state in ("verified", "needs-params", "needs-setup", "broken"):
        print(f"  {state:14s} {counts[state]:4d}")
    print(f"\nraw -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
