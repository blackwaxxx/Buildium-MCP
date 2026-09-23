"""Buildium MCP server.

Exposes the whole Buildium API (462 operations) through a small tool surface:
search -> describe -> call. A handful of curated shortcuts cover the workflows
that come up constantly, so common questions don't need the three-step dance.

Tool names carry a `buildium_` prefix because this server is expected to run
alongside others; bare names like `health` would collide.
"""

from __future__ import annotations

import functools
import inspect
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from .banner import configure_logging, emit_banner
from .client import BuildiumError
from .config import is_download_request_path, is_upload_request_path
from .guards import GuardViolation, check_write, write_mode
from .runtime import (
    Runtime,
    StartupError,
    get_index,
    get_runtime,
    startup_status,
)
from .shaping import (
    is_fixture as _is_fixture,
    list_result as _list_result,
    project as _project,
    split_fixtures as _split_fixtures,
)

mcp = FastMCP("buildium_mcp")


def _startup_err(exc: StartupError) -> dict[str, Any]:
    """What a tool returns when the server is not configured.

    A dict, not an exception: the point of deferring startup is that the model
    gets something it can act on and relay, rather than a transport-level
    failure it can only report as "the server is broken".
    """
    return {
        "ok": False,
        "error": str(exc),
        "type": "StartupError",
        "stage": exc.stage,
        "remedy": exc.remedy,
    }


def _guarded(fn):
    """Catch StartupError and return it as data.

    Wrapped with functools.wraps and deliberately *signature-preserving*:
    FastMCP derives each tool's JSON schema by inspecting the callable, so
    adding a parameter here — for instance injecting the runtime — would leak
    it into the tool's public schema. A test asserts the schemas are unchanged.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except StartupError as exc:
                return _startup_err(exc)
        return wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StartupError as exc:
            return _startup_err(exc)
    return wrapper

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
             "openWorldHint": True}
LOCAL_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
              "openWorldHint": False}
WRITE_CAPABLE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                 "openWorldHint": True}


def _err(exc: Exception) -> dict[str, Any]:
    """Return errors as data. Raising gives the model a stack trace; this gives
    it something it can act on."""
    return {
        "ok": False,
        "error": str(exc),
        "type": type(exc).__name__,
        "status": getattr(exc, "status", None),
    }






# ---------------------------------------------------------------------------
# Core gateway
# ---------------------------------------------------------------------------


@mcp.tool(name="buildium_health", annotations=LOCAL_ONLY)
def health() -> dict[str, Any]:
    """Report which Buildium environment this server is bound to (sandbox,
    production read-only, production read-only with file downloads, or
    production with writes), the active write mode, how many operations are
    indexed, and — if the server is not configured — exactly what to set.

    Only needed before a WRITE, when the environment is genuinely in doubt, or
    when another tool reports a startup problem. Read-only questions do not
    require it.

    Deliberately not wrapped by _guarded: this is the one tool that must answer
    when everything else cannot, so it reports status rather than raising."""
    status = startup_status()
    payload: dict[str, Any] = {"ok": status.ok}
    payload.update(status.as_dict())
    if not status.ok:
        payload["stage"] = status.stage
        payload["error"] = status.error
        payload["remedy"] = status.remedy
    else:
        try:
            payload["fixture_prefix"] = get_runtime().config.fixture_prefix
        except StartupError:
            pass
    return payload


@mcp.tool(name="buildium_list_tags", annotations=LOCAL_ONLY)
@_guarded
def list_tags() -> dict[str, Any]:
    """List every resource area in the Buildium API with its operation count
    (Leases, Work Orders, General Ledger, ...). Use this to orient before
    searching."""
    index = get_index()
    return {"ok": True, "tags": index.tags}


@mcp.tool(name="buildium_search_endpoints", annotations=LOCAL_ONLY)
@_guarded
def search_endpoints(query: str, method: str | None = None, limit: int = 25) -> dict[str, Any]:
    """Find Buildium API endpoints by keyword.

    Searches paths, summaries, tags, and operation IDs across all 462
    operations. Start here when you don't already know the exact path.

    query:  natural keywords, e.g. "work orders", "lease transactions", "gl accounts"
    method: optionally restrict to get/post/put/patch/delete
    """
    index = get_index()
    results = index.search(query, limit=limit, method=method)
    return {"ok": True, "count": len(results), "results": [ep.brief() for ep in results]}


@mcp.tool(name="buildium_describe_endpoint", annotations=LOCAL_ONLY)
@_guarded
def describe_endpoint(method: str, path: str) -> dict[str, Any]:
    """Show the full contract for one endpoint: parameters, request body schema,
    and success response schema, with $refs resolved.

    Call this before buildium_call_endpoint on anything non-trivial — especially
    writes, where the body schema tells you which fields are required.
    """
    index = get_index()
    detail = index.describe(method, path)
    if detail is None:
        return {
            "ok": False,
            "error": f"No such endpoint: {method.upper()} {path}",
            "did_you_mean": [ep.brief() for ep in index.search(path, limit=5)],
        }
    return {"ok": True, **detail}


@mcp.tool(name="buildium_describe_schema", annotations=LOCAL_ONLY)
@_guarded
def describe_schema(name: str) -> dict[str, Any]:
    """Expand a named schema from the spec (e.g. "LeasePostMessage"). Useful when
    buildium_describe_endpoint hit its depth limit and emitted a bare $ref."""
    index = get_index()
    schema = index.schema(name)
    if schema is None:
        return {
            "ok": False,
            "error": f"No schema named {name!r}",
            "did_you_mean": index.schema_names(name, limit=10),
        }
    return {"ok": True, "name": name, "schema": schema}


@mcp.tool(name="buildium_call_endpoint", annotations=WRITE_CAPABLE)
@_guarded
async def call_endpoint(
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    confirm: bool = False,
    all_pages: bool = False,
) -> dict[str, Any]:
    """Call any Buildium endpoint.

    method:  GET, POST, PUT, PATCH, or DELETE
    path:    e.g. "/v1/leases" or "/v1/leases/12345"
    query:   query-string parameters
    body:    JSON request body for writes
    fields:  keep only these top-level fields in the response. Buildium records
             are large — passing e.g. ["Id","Name","PropertyIds"] avoids pulling
             tax IDs and full addresses you did not ask for.
    confirm: required (true) for DELETE
    all_pages: GET only — follow pagination to the end instead of returning the
             first page. Use it whenever you are counting or aggregating; a
             count taken from one page is wrong whenever the collection is
             larger than the page.

    Write guardrails apply — see buildium_health for the active mode. In the
    default 'fixtures' mode, every name in a create payload must carry the
    fixture prefix, nested ones included; a create whose payload has no name
    field at all is allowed against the sandbox but refused against production,
    since nothing on it could carry the prefix. Updates and deletes only work
    on records created this session.
    """
    rt = get_runtime()
    resolved = rt.index.resolve_path(method, path)
    if resolved is None:
        return {
            "ok": False,
            "error": f"{method.upper()} {path} is not in the Buildium spec.",
            "did_you_mean": [e.brief() for e in rt.index.search(path, limit=5)],
        }
    _ep, request_path = resolved

    # Guards and tracking operate on the concrete path — the templated spec path
    # has no record ID in it, so ownership could never be established from it.
    try:
        check_write(method, request_path, body, rt.tracker, confirm=confirm)
    except GuardViolation as exc:
        return _err(exc)

    if all_pages:
        if method.upper() != "GET":
            return {"ok": False,
                    "error": "all_pages applies to GET only; "
                             f"{method.upper()} returns a single result."}
        try:
            records, truncated = await rt.client.get_all_pages(
                request_path, query, max_records=MAX_AUTO_RECORDS
            )
        except BuildiumError as exc:
            return _err(exc)
        return {"ok": True, "count": len(records), "complete": not truncated,
                "truncated_at": MAX_AUTO_RECORDS if truncated else None,
                "pages_followed": True, "data": _project(records, fields)}

    try:
        resp = await rt.client.request(method, request_path, query=query, body=body)
    except BuildiumError as exc:
        return _err(exc)

    # Remember anything we created so updates/deletes on it are permitted later.
    if method.upper() == "POST" and isinstance(resp.data, dict):
        rt.tracker.record(request_path, resp.data.get("Id"), body)

    return {"ok": True, "status": resp.status, "data": _project(resp.data, fields)}


@mcp.tool(name="buildium_created_fixtures", annotations=LOCAL_ONLY)
@_guarded
def created_fixtures() -> dict[str, Any]:
    """List records created during this session, grouped by collection. These are
    the only records that updates and deletes are permitted against in 'fixtures'
    mode. Also appended to created-records.log (see buildium_health for the
    path) so they can be cleaned up after the process is gone."""
    rt = get_runtime()
    return {"ok": True, "created": rt.tracker.summary(), "log": str(rt.config.artifact_log)}


# ---------------------------------------------------------------------------
# Files — Buildium's two-step signed-URL flow
# ---------------------------------------------------------------------------


@mcp.tool(name="buildium_upload_file", annotations=WRITE_CAPABLE)
@_guarded
async def upload_file(
    file_path: str,
    title: str,
    category_id: int,
    entity_type: str = "Rental",
    entity_id: int | None = None,
    description: str | None = None,
    upload_path: str = "/v1/files/uploads",
) -> dict[str, Any]:
    """Upload a local file to Buildium, handling both steps of its upload flow.

    Bytes do not travel through the Buildium API. Buildium issues a short-lived
    AWS presigned PUT URL, and the file is sent there directly. Doing that by
    hand with buildium_call_endpoint does not work — call_endpoint would post
    the metadata and hand you a URL it cannot then PUT to. Use this instead.

    file_path:   path to the file on this machine
    title:       the file's title in Buildium. In 'fixtures' write mode this
                 must start with the fixture prefix (see buildium_health).
    category_id: from GET /v1/files/categories — required, and Buildium
                 rejects the upload without a real one.
    entity_type: what the file is attached to — Rental, Lease, Tenant, Vendor,
                 Association, RentalOwner, RentalUnit, and so on.
    entity_id:   the ID of that record.
    upload_path: for files belonging to a bill, check, or task history, pass
                 that resource's own uploads path, e.g.
                 "/v1/bills/123/files/uploads". Only Buildium's seven
                 upload-request endpoints are accepted here, in every mode.
    """
    rt = get_runtime()
    if not is_upload_request_path(upload_path if upload_path.startswith("/")
                                  else "/" + upload_path):
        return {
            "ok": False,
            "error": f"{upload_path!r} is not one of Buildium's upload-request "
                     "endpoints (…/files/uploads or …/images/uploads with numeric "
                     "ids). This tool only starts uploads; use "
                     "buildium_call_endpoint for other requests.",
        }
    source = Path(file_path).expanduser()
    if not source.is_file():
        return {"ok": False, "error": f"No file at {source}"}

    metadata: dict[str, Any] = {
        "EntityType": entity_type,
        "FileName": source.name,
        "Title": title,
        "CategoryId": category_id,
    }
    if entity_id is not None:
        metadata["EntityId"] = entity_id
    if description:
        metadata["Description"] = description

    try:
        check_write("POST", upload_path, metadata, rt.tracker, confirm=False)
    except GuardViolation as exc:
        return _err(exc)

    try:
        payload = source.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"Could not read {source}: {exc}"}

    try:
        result = await rt.client.upload_file(upload_path, metadata, payload, source.name)
    except BuildiumError as exc:
        return _err(exc)
    return {"ok": True, **result, "title": title}


@mcp.tool(name="buildium_download_file", annotations=READ_ONLY)
@_guarded
async def download_file(
    file_id: int,
    save_to: str,
    download_path: str | None = None,
) -> dict[str, Any]:
    """Download a Buildium file to this machine, handling both steps.

    Buildium issues a download URL that expires after five minutes and serves
    the bytes from separate storage, so this cannot be done with
    buildium_call_endpoint.

    Note this is refused when the server runs in production-readonly mode:
    Buildium models a download request as a POST, and that mode blocks every
    POST at the transport layer without exception. Reading file *metadata* via
    GET /v1/files/{id} still works.

    file_id:       from GET /v1/files
    save_to:       where to write the file on this machine
    download_path: for a file belonging to a bill, check, or task history, that
                   resource's own download path, e.g.
                   "/v1/bills/123/files/456/downloadrequest". Only Buildium's
                   seven download-request endpoints are accepted here, in
                   every mode.
    """
    rt = get_runtime()
    path = download_path or f"/v1/files/{file_id}/downloadrequest"
    if not path.startswith("/"):
        path = "/" + path
    if not is_download_request_path(path):
        return {
            "ok": False,
            "error": f"{path!r} is not one of Buildium's download-request "
                     "endpoints (…/downloadrequest or …/downloadrequests with "
                     "numeric ids). This tool only fetches files; use "
                     "buildium_call_endpoint for other requests.",
        }
    try:
        data, content_type = await rt.client.download_file(path)
    except BuildiumError as exc:
        return _err(exc)

    target = Path(save_to).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        return {"ok": False, "error": f"Downloaded {len(data)} bytes but could not "
                                      f"write {target}: {exc}"}
    return {"ok": True, "saved_to": str(target), "bytes": len(data),
            "content_type": content_type}


# ---------------------------------------------------------------------------
# Curated shortcuts — the handful of reads that come up constantly
# ---------------------------------------------------------------------------


# Ceiling on an auto-paginated fetch. High enough for every collection in a
# normal portfolio, low enough that a mistake costs seconds rather than
# thousands of requests.
MAX_AUTO_RECORDS = 1000


async def _get_list(
    rt: Runtime,
    path: str, limit: int, offset: int, extra: dict[str, Any] | None = None,
    fields: list[str] | None = None, all_pages: bool = False,
    exclude_fixtures: bool = False,
) -> dict[str, Any]:
    query: dict[str, Any] = {k: v for k, v in (extra or {}).items() if v is not None}

    if all_pages:
        try:
            records, truncated = await rt.client.get_all_pages(
                path, query, page_size=max(limit, 100), max_records=MAX_AUTO_RECORDS
            )
        except BuildiumError as exc:
            return _err(exc)
        real, fixtures = _split_fixtures(records, rt.config.fixture_prefix)
        kept = real if exclude_fixtures else records
        result: dict[str, Any] = {
            "ok": True,
            "count": len(kept),
            "complete": not truncated,
            "truncated_at": MAX_AUTO_RECORDS if truncated else None,
            "pages_followed": True,
            "data": _project(kept, fields),
        }
        if fixtures:
            result["fixture_count"] = len(fixtures)
            result["fixtures_excluded"] = exclude_fixtures
            if not exclude_fixtures:
                result["fixture_note"] = (
                    f"{len(fixtures)} of these {len(records)} records are test "
                    f"fixtures (name starts with {rt.config.fixture_prefix!r}). "
                    "Pass exclude_fixtures=true to count only genuine data."
                )
        return result

    query.update({"limit": limit, "offset": offset})
    try:
        resp = await rt.client.request("GET", path, query=query)
    except BuildiumError as exc:
        return _err(exc)
    return _list_result(resp.data, limit, offset, fields,
                        fixture_prefix=rt.config.fixture_prefix,
                        exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_list_rentals", annotations=READ_ONLY)
@_guarded
async def list_rentals(limit: int = 50, offset: int = 0,
                       fields: list[str] | None = None,
                       all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List rental properties. Pass `fields` to narrow large records.

    Set all_pages=true to follow pagination to the end in one call — do that
    whenever you are counting or aggregating, since a single page is only the
    first 50 records and a count taken from it will be wrong."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/rentals", limit, offset, fields=fields,
                           all_pages=all_pages,
                           exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_get_rental", annotations=READ_ONLY)
@_guarded
async def get_rental(rental_id: int, fields: list[str] | None = None) -> dict[str, Any]:
    """Get one rental property by ID."""
    rt = get_runtime()
    try:
        resp = await rt.client.request("GET", f"/v1/rentals/{rental_id}")
    except BuildiumError as exc:
        return _err(exc)
    return {"ok": True, "data": _project(resp.data, fields)}


@mcp.tool(name="buildium_list_units", annotations=READ_ONLY)
@_guarded
async def list_units(property_id: int | None = None, limit: int = 50, offset: int = 0,
                     fields: list[str] | None = None,
                     all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List rental units, optionally filtered to one property.

    Set all_pages=true when counting or aggregating; one page is not the
    whole collection."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/rentals/units", limit, offset,
                           {"propertyids": property_id}, fields, all_pages,
                           exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_list_leases", annotations=READ_ONLY)
@_guarded
async def list_leases(property_id: int | None = None, lease_status: str | None = None,
                      limit: int = 50, offset: int = 0,
                      fields: list[str] | None = None,
                      all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List leases. lease_status is one of Active, Future, Past, Expired.

    Each row already carries the rent terms under `AccountDetails` (including
    `AccountDetails.Rent`, the recurring monthly amount) and the lease dates.
    You do NOT need to open the transaction ledger to read a lease's rent —
    buildium_list_lease_transactions is for actual posted charges and payments,
    which is a different question.

    For who is on each lease, use buildium_lease_roster.

    Set all_pages=true when counting or aggregating across every lease."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/leases", limit, offset,
                           {"propertyids": property_id, "leasestatuses": lease_status},
                           fields, all_pages, exclude_fixtures)


@mcp.tool(name="buildium_get_lease", annotations=READ_ONLY)
@_guarded
async def get_lease(lease_id: int, fields: list[str] | None = None) -> dict[str, Any]:
    """Get one lease by ID, including tenants and rent terms."""
    rt = get_runtime()
    try:
        resp = await rt.client.request("GET", f"/v1/leases/{lease_id}")
    except BuildiumError as exc:
        return _err(exc)
    return {"ok": True, "data": _project(resp.data, fields)}


@mcp.tool(name="buildium_list_lease_transactions", annotations=READ_ONLY)
@_guarded
async def list_lease_transactions(lease_id: int, limit: int = 50, offset: int = 0,
                                  fields: list[str] | None = None,
                                  all_pages: bool = False,
                                  exclude_fixtures: bool = False) -> dict[str, Any]:
    """List financial transactions (posted charges and payments) for a lease.

    For the lease's recurring rent amount use buildium_list_leases instead —
    it is already on every row under AccountDetails.Rent.

    Set all_pages=true when totalling a ledger."""
    rt = get_runtime()
    return await _get_list(rt, f"/v1/leases/{lease_id}/transactions", limit, offset,
                           fields=fields, all_pages=all_pages,
                           exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_list_work_orders", annotations=READ_ONLY)
@_guarded
async def list_work_orders(limit: int = 50, offset: int = 0,
                           fields: list[str] | None = None,
                           all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List work orders (maintenance jobs).

    Set all_pages=true when counting or aggregating."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/workorders", limit, offset, fields=fields,
                           all_pages=all_pages,
                           exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_list_tenants", annotations=READ_ONLY)
@_guarded
async def list_tenants(limit: int = 50, offset: int = 0,
                       fields: list[str] | None = None,
                       all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List rental tenants.

    Set all_pages=true when counting or aggregating."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/leases/tenants", limit, offset, fields=fields,
                           all_pages=all_pages,
                           exclude_fixtures=exclude_fixtures)


@mcp.tool(name="buildium_lease_roster", annotations=READ_ONLY)
@_guarded
async def lease_roster(
    lease_id: int | None = None,
    property_id: int | None = None,
    limit: int = 100,
    exclude_fixtures: bool = False,
) -> dict[str, Any]:
    """Who is on which lease — the lease-to-tenant join, done in one call.

    Use this for any "who lives in / who is on lease X" question, and for
    counting co-tenants.

    Buildium makes this awkward: the lease list does not reliably populate tenant
    names, and the tenant endpoint has no lease filter — so answering it directly
    means pulling every lease one at a time. Tenant records do carry their lease
    membership, so this fetches them once and inverts the mapping locally.

    Every tenant is read, following pagination, up to 1000; `complete` says
    whether that covered them all. Narrow with property_id if it did not.

    lease_id:    restrict to a single lease
    property_id: restrict to leases at one property
    limit:       page size used while fetching tenants (1-1000). It does not
                 cap the roster.
    exclude_fixtures: drop tenants created by test tooling (names starting with
                 the fixture prefix — see buildium_health). This sandbox
                 accumulates such records permanently, because Buildium offers
                 DELETE on only 14 of its 462 operations. When any are present
                 the response says so, so a count is never silently wrong.
    """
    rt = get_runtime()
    query: dict[str, Any] = {}
    if property_id is not None:
        query["propertyids"] = property_id
    # All pages, not one: a lease's tenants can sit anywhere in the tenant
    # list, so a single page undercounts every portfolio larger than it and
    # answers a lease_id question with an empty roster.
    try:
        rows, truncated = await rt.client.get_all_pages(
            "/v1/leases/tenants", query,
            page_size=min(max(limit, 1), 1000), max_records=MAX_AUTO_RECORDS,
        )
    except BuildiumError as exc:
        return _err(exc)
    prefix = rt.config.fixture_prefix
    fixture_tenants = 0
    roster: dict[int, list[dict[str, Any]]] = {}
    for tenant in rows:
        fixture = _is_fixture(tenant, prefix)
        if fixture:
            fixture_tenants += 1
            if exclude_fixtures:
                continue
        person = {
            "TenantId": tenant.get("Id"),
            "Name": f"{tenant.get('FirstName', '')} {tenant.get('LastName', '')}".strip(),
            "Email": tenant.get("Email"),
        }
        if fixture:
            person["IsFixture"] = True
        for lease in tenant.get("Leases") or []:
            lid = lease.get("Id")
            if lid is None:
                continue
            roster.setdefault(lid, []).append(person)

    if lease_id is not None:
        roster = {k: v for k, v in roster.items() if k == lease_id}

    multi = sorted(k for k, v in roster.items() if len(v) > 1)
    fixture_leases = sorted(
        k for k, v in roster.items()
        if len(v) > 1 and any(t.get("IsFixture") for t in v)
    )

    out: dict[str, Any] = {
        "ok": True,
        "complete": not truncated,
        "truncated_at": MAX_AUTO_RECORDS if truncated else None,
        "lease_count": len(roster),
        "tenants_seen": len(rows),
        "multi_tenant_leases": multi,
        "roster": [
            {"LeaseId": k, "TenantCount": len(v), "Tenants": v}
            for k, v in sorted(roster.items())
        ],
    }
    if truncated:
        out["truncation_note"] = (
            f"Stopped after {MAX_AUTO_RECORDS} tenants with more remaining, so "
            "leases whose tenants lie past that point are missing or "
            "undercounted. Pass property_id to narrow the query."
        )
    if fixture_tenants:
        out["fixture_tenants"] = fixture_tenants
        out["fixtures_excluded"] = exclude_fixtures
        if not exclude_fixtures:
            out["multi_tenant_leases_excluding_fixtures"] = [
                k for k in multi if k not in fixture_leases
            ]
            out["fixture_note"] = (
                f"{fixture_tenants} of {len(rows)} tenants are test fixtures "
                f"(name starts with {prefix!r}), and {len(fixture_leases)} of the "
                f"{len(multi)} multi-tenant leases exist only because of them. "
                "Counting genuine portfolio data means using "
                "multi_tenant_leases_excluding_fixtures, or passing "
                "exclude_fixtures=true."
            )
    return out


@mcp.tool(name="buildium_list_gl_accounts", annotations=READ_ONLY)
@_guarded
async def list_gl_accounts(limit: int = 100, offset: int = 0,
                           fields: list[str] | None = None,
                           all_pages: bool = False,
                       exclude_fixtures: bool = False) -> dict[str, Any]:
    """List general ledger accounts. You need these IDs to post rent charges and
    other financial transactions.

    Set all_pages=true when counting or aggregating."""
    rt = get_runtime()
    return await _get_list(rt, "/v1/glaccounts", limit, offset, fields=fields,
                           all_pages=all_pages,
                           exclude_fixtures=exclude_fixtures)


def main() -> None:
    """Start the server.

    Deliberately does not sys.exit on a configuration failure. A non-zero exit
    makes the MCP client mark the server dead, and the user never gets to call
    buildium_health to find out why. Instead: say what is wrong on stderr, start
    anyway, and let every tool return the remedy.
    """
    configure_logging()
    try:
        emit_banner(startup_status())
    except Exception as exc:  # the banner must never stop the server
        logging.getLogger("buildium_mcp").warning("could not render banner: %s", exc)
    mcp.run()


if __name__ == "__main__":
    main()
