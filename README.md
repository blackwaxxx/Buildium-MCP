# buildium-mcp

An MCP server for the [Buildium](https://www.buildium.com/) Open API. All **462
operations** across 42 resource areas, exposed through **20 tools**.

Sandbox by default. Reaching production takes two deliberate settings, and the
read-only modes block writes in the transport rather than by policy.

**[COVERAGE.md](COVERAGE.md)** records what is actually proven against a live
sandbox: **218 of 462 operations verified, 0 broken.** That number is
178 GET operations + 40 writes across twelve entity families. The remaining
GETs are marked `needs-setup` — the sandbox holds no record of the required
type, so there was no id to call them with — and each of the 184 unattempted
writes carries its own stated reason.

> Unofficial. Not affiliated with, endorsed by, or sponsored by Buildium.
> "Buildium" is a trademark of its owner. See [NOTICE](NOTICE) for the
> provenance of the bundled OpenAPI document.

## Why 20 tools and not 462

The Buildium spec is 298 paths, 462 operations, 519 schemas. One-tool-per-operation
is the obvious approach and it fails at this size — the tool list alone burns tens
of thousands of context tokens before the model does any work, and selection
accuracy collapses past a few dozen tools.

So the spec is indexed at runtime instead:

```
search_endpoints("work orders")      → ranked candidates
describe_endpoint("POST", "/v1/...") → params + body schema, $refs resolved
get("/v1/...")                       → any read
call_endpoint("POST", "/v1/...", …)  → a write
```

Reads and writes are separate tools on purpose. `buildium_get` is annotated
read-only, so a client can approve it once, while `buildium_call_endpoint`
still asks about every write.

Ten curated shortcuts (`list_leases`, `list_work_orders`, `list_gl_accounts`, …)
cover frequent reads so routine questions skip the three-step path. Two file
tools exist because Buildium's file flow cannot be driven through the
gateway at all — see below.

## Setup

You need a Buildium **Premium** subscription with the Open API enabled
(Settings → Application settings → Api settings) and an API key created under
Settings → Developer Tools.

### Claude Desktop: one click

Download `buildium-mcp-<version>.mcpb` from the releases page and double-click
it (or drag it onto the Claude Desktop window). Claude Desktop asks for your
Client ID and Client Secret in a settings form, stores them securely, and
installs everything else itself — including Python, if your machine has none.
Sandbox is the default; the same form has a "Connect to production" toggle for
when you are ready, and separate toggles for allowing changes and file
downloads there. The install dialog labels the bundle *unsigned* and says it
has access to your computer; both are standard for every local extension — see
[mcpb/](mcpb/) for what this one actually touches and why it is not signed.

### Any other MCP client

Requires Python 3.11+.

```bash
pip install buildium-mcp
```

Releases are published to [PyPI](https://pypi.org/project/buildium-mcp/) from
this repository's release workflow, with the same files and checksums as the
[GitHub releases](https://github.com/blackwaxxx/Buildium-MCP/releases). To run
unreleased code, install from GitHub instead:
`pip install "git+https://github.com/blackwaxxx/Buildium-MCP"`.

Sandbox is a **separate Buildium account** from production — production keys do
not authenticate against `apisandbox.buildium.com`.

### Credentials

The preferred way is your MCP client's own `env` block, so the secret lives
with the rest of your client configuration:

```json
{
  "mcpServers": {
    "buildium": {
      "command": "buildium-mcp",
      "env": {
        "BUILDIUM_CLIENT_ID": "...",
        "BUILDIUM_CLIENT_SECRET": "..."
      }
    }
  }
}
```

A `.env` file works too. Three locations are searched, highest priority first,
and the real process environment beats all of them:

1. `$BUILDIUM_ENV_FILE`
2. the root of a source checkout, if this is running from one — found from the
   package's own location, so it works whatever working directory the MCP
   client picks
3. your platform config directory — `buildium_health` reports which files were
   actually read, under `env_files_loaded`

Only `BUILDIUM_*` variables are read from these files; anything else in them is
ignored. The working directory is not searched. An MCP client starts the server
wherever it likes, often inside a project whose `.env` has nothing to do with
this one, and variables such as `HTTPS_PROXY` in a file like that could redirect
the traffic that carries your API secret.

```
BUILDIUM_CLIENT_ID=...
BUILDIUM_CLIENT_SECRET=...
```

`chmod 600` it. If the server cannot find credentials it still starts, and
`buildium_health` reports exactly what is missing and where it looked — the
spec-only tools (`search_endpoints`, `describe_endpoint`, …) keep working
meanwhile.

### From a checkout

```bash
git clone https://github.com/blackwaxxx/Buildium-MCP && cd Buildium-MCP
uv venv --python 3.11 && uv pip install -e ".[dev]"
```

### Files it writes

| | Default | Override |
|---|---|---|
| `.env` | platform config dir | `BUILDIUM_ENV_FILE`, `BUILDIUM_CONFIG_DIR` |
| `run.log` (request audit) | platform state dir | `BUILDIUM_RUN_LOG`, `BUILDIUM_STATE_DIR` |
| `created-records.log` | platform state dir | `BUILDIUM_ARTIFACT_LOG` |
| downloaded files | `~/Downloads/Buildium` | `BUILDIUM_DOWNLOAD_DIR` |

The logs and downloads are created readable by you only (`0600`). Set either
log variable to `off` to disable it. If the state directory is not
writable the server still runs; `buildium_health` reports `audit_log: null`
with the reason rather than pretending to log.

## Run

```bash
.venv/bin/python -m buildium_mcp.server   # stdio
```

Register it with any MCP client:

```json
{
  "command": "buildium-mcp"
}
```

or, from a checkout:

```json
{
  "command": "/path/to/buildium-mcp/.venv/bin/python",
  "args": ["-m", "buildium_mcp.server"]
}
```

The OpenAPI spec ships inside the package, so it is found the same way in a
wheel and in an editable checkout. Nothing is resolved relative to a repo root.

## Write safety

`BUILDIUM_WRITE_MODE` — default `fixtures`:

| | `fixtures` | `open` |
|---|---|---|
| Create, payload has a name | every name in it must start with `ZZ-MCPTEST-` | unrestricted |
| Create, payload has no name | sandbox host only | unrestricted |
| Create under an existing record | off the sandbox, only under records created this session | unrestricted |
| Update / delete | only records created this session | unrestricted |
| Delete | requires `confirm=true` | requires `confirm=true` |
| Audit | always | always |

`fixtures` is the posture for unattended or agent-driven use: an agent working
alone cannot update or delete a record it did not create. Off the sandbox that
extends to creates under an existing record — a renewal of a lease, a charge or
a note on it — which must hang off a record created this session. What it does
not check is a record the payload merely names, such as the `UnitId` of a new
lease; see [KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md). Switch to `open` for
real work.

`BUILDIUM_FIXTURE_PREFIX` changes the prefix. A blank value means the default,
since every name starts with an empty string.

"Every name in it" means the whole payload, not just the top level. Creating a
lease creates its tenants, so `Tenants[0].FirstName` is checked the same way the
record's own `Name` is. A refusal names the exact field.

Most write endpoints have no name field anywhere: charges, payments, journal
entries, checks, notes. 84 of the 119 `POST` operations in the spec. Nothing on
those payloads can carry the prefix, so this mode cannot promise the record it
creates will be identifiable, and it does not pretend otherwise. Against the
sandbox they are allowed, because the data is disposable. Against a production
host they are refused; use `open` to create live records deliberately.

Note that this turns on the host, not on the mode: `production-write` aimed at
the sandbox is still writing to the sandbox. The same payload is also refused
when it is too large or too deeply nested to read in full, since "I could not
check" must not resolve to "looked fine".

Every request goes to `run.log`; every created record ID goes to
`created-records.log`. Credentials are never written to either.

## Deployment mode

`BUILDIUM_DEPLOYMENT_MODE` — default `sandbox`:

| | Reachable hosts | Writes | File downloads |
|---|---|---|---|
| `sandbox` (default) | sandbox only | allowed, further constrained by `BUILDIUM_WRITE_MODE` | yes |
| `production-readonly` | sandbox + production | **blocked in the transport** | no |
| `production-readonly-files` | sandbox + production | **blocked in the transport** | yes, 7 endpoints |
| `production-write` | sandbox + production | allowed | yes |

An unrecognized value is a startup error listing the valid ones — a typo must
not silently pick a mode.

**Reaching production takes two independent things**, and neither alone is
enough: this variable *and* a `BUILDIUM_BASE_URL` naming a production host.
Setting the mode changes what is *permitted*, never what is *targeted*, so a
stray mode variable cannot redirect a sandbox server at live data.

The read-only modes are not a policy check a caller can talk its way past.
`ReadOnlyTransportGuard` sits in the httpx transport slot — the last code that
runs before a socket is opened. It lets only `GET`, `HEAD` and `OPTIONS` through
(an allowlist, so an unknown or malformed verb is refused too), and it refuses
any request whose host is not a Buildium host over https, whatever the method.
Calling `client.post()` directly, hand-building an `httpx.Request`, or bypassing
`BuildiumClient` entirely all hit the same wall. Tested by doing exactly that.

### Why `production-readonly-files` exists

Buildium issues a file download by POSTing for a short-lived signed URL, so a
server that refuses every POST cannot read a lease PDF. Rather than weaken
`production-readonly`, this mode exempts **exactly seven** operations — the
`downloadrequest` and `downloadrequests` endpoints for files, bill files, task
files, rental and unit images, check attachments, and architectural-request
files. Everything else is still refused in the transport.

The exemption is scoped by an anchored pattern matched against the raw,
still-percent-encoded wire path, so `%2f`, `%2e%2e` and `%00` cannot smuggle a
different path through it, and the host is checked too — an absolute URL cannot
aim an allowlisted path at a server of the caller's choosing. A test iterates
every POST in the spec and asserts precisely these seven are reachable.

Run read-only for a while before considering `production-write`. The banner on
stderr names the active mode and where it came from on every start.

Verify the guarantee yourself — runs against the sandbox, writes nothing:

```bash
.venv/bin/python tests/demo_readonly.py
```

## Tests

```bash
pytest                                 # offline, no credentials
.venv/bin/python tests/stdio_check.py               # live sandbox
```

The unit suite (379 tests) covers spec indexing, path resolution, response
shaping, `allOf` flattening, auto-pagination, deprecation handling, error hints,
and every guardrail branch — all four deployment modes, the download allowlist
proved exhaustively against the spec, which `.env` files are read and what they
may set, and the packaging and startup paths — with no network access. `tests/conftest.py` isolates it from any `.env` on the
machine, so the offline suite cannot accidentally make a live call.

Coverage walks, which do hit the sandbox:

```bash
.venv/bin/python tests/coverage_matrix.py   # all 238 GETs; read-only by construction
.venv/bin/python tests/coverage_writes.py   # curated write scenarios, ~20 records
.venv/bin/python tests/render_coverage.py   # regenerates COVERAGE.md
```

The integration suite drives the server over real stdio JSON-RPC and exercises reads, error mapping,
all four guardrail refusal paths, and a full create/read/update/delete cycle
against live sandbox records. Requires working sandbox credentials.

## Tools

All tools carry a `buildium_` prefix — this server is meant to run alongside
others, and bare names like `health` would collide.

**Gateway** — `buildium_health`, `buildium_list_tags`, `buildium_search_endpoints`,
`buildium_describe_endpoint`, `buildium_describe_schema`, `buildium_get`,
`buildium_call_endpoint`, `buildium_created_fixtures`

**Files** — `buildium_upload_file`, `buildium_download_file`

**Shortcuts** — `buildium_list_rentals`, `buildium_get_rental`, `buildium_list_units`,
`buildium_list_leases`, `buildium_get_lease`, `buildium_list_lease_transactions`,
`buildium_list_work_orders`, `buildium_list_tenants`, `buildium_list_gl_accounts`,
`buildium_lease_roster`

`buildium_lease_roster` answers "who is on lease X" and "how many leases have
co-tenants" in one call. Buildium's lease list does not reliably populate tenant
names and its tenant endpoint has no lease filter, so without this the join costs
one request per lease — measured at 24 calls for a single question before it
existed, 1 after.

It is built for large accounts. It reads every tenant, following pagination up
to 100,000, and says in `complete` whether that was all of them. Given a
`lease_id` it reads only that lease's unit, which is two requests however big
the account is. `lease_status=Active` skips years of past tenants. Past 300
leases it returns counts (`multi_tenant_lease_count` and friends) instead of the
tenant-by-tenant listing, which would be too large for one tool result; filter
by property or lease for names.

Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`,
`idempotentHint`, `openWorldHint`) so a client can tell reads from writes without
parsing descriptions.

### Keeping responses small

Buildium records are fat — an owner carries tax IDs, fax numbers, and mailing
addresses. Pass `fields` to keep only what you need:

```json
{"path": "/v1/rentals/owners",
 "fields": ["Id", "FirstName", "LastName", "PropertyIds"]}
```

### Files

Buildium never moves bytes through its API. An upload request returns an AWS S3
**presigned PUT** URL and a set of `x-amz-meta-*` headers; the bytes go straight
to storage, and every signed header must be reproduced exactly or it fails with
`SignatureDoesNotMatch`. Downloads mirror it through a URL that expires after
five minutes. `buildium_upload_file` and `buildium_download_file` run both
halves. Each accepts a path for the resource the file belongs to, and each is
confined to Buildium's seven upload or seven download endpoints in every mode —
neither is a way to POST anywhere else.

The signed URL points at a third-party host, so the transfer carries **no
Buildium credentials** — sending the client secret to a host named by an API
response would leak it wherever that response pointed.

On this machine, downloads go into one folder and nowhere else:
`~/Downloads/Buildium`, or `BUILDIUM_DOWNLOAD_DIR`, which `buildium_health`
reports. `save_to` is a name or a path inside it; a path outside it is refused
before anything is fetched, symlinks included, and an existing file is kept
unless you pass `overwrite=true`. The reason is prompt injection: text in a work
order could otherwise have the model save a tenant-uploaded file over
`~/.zshrc`. For the same reason uploads refuse hidden files and folders
(`~/.ssh`, `.env`), anything named `*.env`, and this server's own configuration
and logs.

Note that `buildium_download_file` does not work under `PRODUCTION_READONLY`:
Buildium models a download request as a POST, and that mode blocks every POST
without exception. Keeping the guarantee absolute was worth more than the
exception; file metadata still reads fine over GET.

### Pagination

List tools return pagination metadata alongside the rows:

```json
{"ok": true, "count": 50, "limit": 50, "offset": 0,
 "has_more": true, "next_offset": 50, "data": [...]}
```

`has_more` is inferred from a full page — Buildium returns no total count — so it
is a hint, not a guarantee.

Pass `all_pages=true` to follow pagination to the end in one call, which is what
you want whenever you are counting or aggregating. It returns `complete` rather
than `has_more`, caps at 1000 records, and says so explicitly if it truncated:

```json
{"ok": true, "count": 55, "complete": true, "pages_followed": true, "data": [...]}
```

The cap is about the size of the answer, not the API. A lease record is about
1.6 KB, so a thousand of them is already far more than an MCP client accepts as
one tool result.

To count, pass `count_only=true` instead. It follows every page, up to 100,000
records, and returns only the number, so "how many active leases" is one call
in any account:

```json
{"ok": true, "count": 4500, "complete": true, "pages_followed": true, "count_only": true}
```

It is on every list tool and on `buildium_get` for any collection, and honours `exclude_fixtures`. For totals or other figures that
need the records themselves, past 1000 of them, narrow the query with the
tool's filters and `fields`, or page by hand with `limit` (up to 1000) and
`offset`. `buildium_lease_roster` is not bound by the cap either — see above.

### Test fixtures

Buildium supports `DELETE` on only 14 of its 462 operations, so any account
that has been tested against accumulates test records permanently — and every
count over it becomes ambiguous.

Rather than leave that to inference, list tools and `buildium_lease_roster`
report `fixture_count` whenever records matching the fixture prefix are
present, along with a note saying what it means. `buildium_lease_roster` also
precomputes `multi_tenant_lease_count_excluding_fixtures`, and the matching
lease ids when the roster is small enough to list. Pass
`exclude_fixtures=true` to filter them out.

Nothing is dropped unless you ask, and `next_offset` keeps counting the rows
the server returned rather than the ones left after filtering, so excluding
fixtures never causes the next page to skip records.

### Deprecated endpoints

Sixteen operations — every appliance path — **start returning 410 Gone on
2026-10-19**. `search_endpoints` and `describe_endpoint` report `deprecated:
true` with the retirement date and the replacement path, and deprecated
endpoints rank below equivalent live ones without being hidden: at the time of
writing the replacement API returns nothing, so the deprecated endpoints are
still the only place the records exist.

## Notes

Buildium authenticates with two static headers — `x-buildium-client-id` and
`x-buildium-client-secret`. There is no OAuth flow, no token endpoint, and no
refresh, despite what some third-party integrations claim.

Only 14 of the 462 operations support `DELETE`. Most resources — vendor
categories among them — can be created but never removed via the API.

Unaffiliated with Buildium, LLC.
