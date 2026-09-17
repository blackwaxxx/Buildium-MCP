# Architecture

Why this server is shaped the way it is. For what it *does*, see the README;
for what it deliberately does not do, see [KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md).

## 19 tools, not 462

One tool per operation is the obvious design and it fails at this size. The
Buildium spec is 298 paths, 462 operations, 519 schemas; the tool list alone
would burn tens of thousands of context tokens before the model does any work,
and selection accuracy collapses well before that.

So the spec is indexed at runtime and navigated in three steps:

```
search_endpoints("work orders")      → ranked candidates
describe_endpoint("POST", "/v1/...") → params + body schema, $refs resolved
call_endpoint("POST", "/v1/...", …)  → the actual call
```

Ten curated shortcuts cover the reads that come up constantly, so routine
questions skip the dance. Two file tools exist because Buildium's file flow
cannot be expressed through `call_endpoint` at all.

Indexing the whole 2.7MB document costs about 20ms at startup, so nothing here
is lazy for performance reasons. `$ref` resolution *is* on demand, capped at
depth 6 with cycle breaking, because a fully resolved schema graph is both
enormous and circular.

## Layers

```
server.py    19 @mcp.tool functions; no logic beyond shaping a response
runtime.py   staged, deferred startup; the only place tools get their state
config.py    modes, host allowlist, the download allowlist, the one decision fn
client.py    HTTP, auth, retries, pagination, the transport guard
guards.py    write-mode enforcement and the fixture tracker
spec.py      OpenAPI indexing, search, $ref resolution
shaping.py   pure response projection and fixture partitioning
paths.py     where .env, the spec, and the logs live
banner.py    the startup banner (pure render + an emit)
```

`shaping.py` is separate and import-free on purpose: it is the part that can be
unit-tested without constructing a config.

## Three enforcement points, one decision

`config.request_permitted(mode, method, path)` is the only function that decides
whether a request may leave the process. Three places call it:

1. **`ReadOnlyTransportGuard`** (`client.py`) — the real boundary. A transport
   is the last code that runs before httpx opens a socket, so this cannot be
   bypassed by calling `client.post()`, by hand-building a `Request` and calling
   `send()`, or by reaching past `BuildiumClient` entirely. It judges methods by
   allowlist — only `GET`, `HEAD` and `OPTIONS` pass — so `TRACE`, `PROPFIND` or
   a mistyped `P0ST` are refused rather than waved through as "not a write". It
   is installed only in the two read-only modes; in `sandbox` and
   `production-write` the client talks to httpx's default transport.
2. **`BuildiumClient.request`** — advisory. Runs on the caller's un-normalized
   string purely to produce a clean error and an audit record, so it may be
   marginally stricter than the transport. That is fine.
3. **`guards.check_write`** — the write-mode layer, which also has to know that
   a permitted download is not a "write" for fixture purposes.

Having one function rather than three conditionals is the point: three copies of
a security decision drift, and the drift is silent.

### Why the guard reads `raw_path`

The guard matches `request.url.raw_path`, not `url.path`. `raw_path` is what
goes on the wire and is still percent-encoded, so `%2f`, `%2e%2e` and `%00`
cannot become separators and dot segments *after* the allowlist has approved
the string. `url.path` is decoded, which would let `%2f..%2fleases` turn into
`/../leases` inside a value already judged safe.

It also binds the host and scheme, for every method. An absolute URL handed
to httpx retargets the request away from `base_url`, so a path-only allowlist
would let a caller aim a permitted download path at a server of their choosing —
and since the client's default headers carry the credentials, a retargeted `GET`
would hand them to that server.

### The file helpers are confined separately

`buildium_download_file` and `buildium_upload_file` take their request path from
the caller, and they bypass the spec lookup and fixture tracker that
`call_endpoint` applies. So `BuildiumClient.download_file` refuses any path that
is not one of the seven download endpoints, and `upload_file` any path that is
not one of the seven upload endpoints, in every mode and before any request is
built. Without that, in a write-capable mode the read-only-annotated download
tool was an arbitrary empty-body `POST`.

## Policy and scope are kept apart

Which modes may download is a property on `DeploymentMode`. What counts as a
download is `DOWNLOAD_REQUEST_PATHS` plus an anchored regex. Keeping them in
separate places means widening one cannot accidentally widen the other, and it
makes the matcher a pure function of a string — which is what lets it be fuzzed
without constructing a client.

The path set is re-derived from the spec by a test, so a spec revision that adds
an eighth download endpoint fails the build rather than quietly leaving that
file type unreachable.

## The enum fails closed

`writes_allowed` and `is_production` are allowlists — `self in (SANDBOX,
PRODUCTION_WRITE)`, not `self is not PRODUCTION_READONLY`. Phrased as denylists,
adding a mode silently grants it write access, because every site that decides
whether to install a guard asks `writes_allowed` and nothing iterates the enum.
That is not hypothetical: it is exactly what happened when
`production-readonly-files` was first added, and the fix is why two tests now
iterate every member and assert exact sets.

## Two factors to reach production

`BUILDIUM_DEPLOYMENT_MODE` grants *permission*. `BUILDIUM_BASE_URL` chooses the
*target*. Neither alone reaches live data, and the host check runs in every mode.

This is what survives of the original design, in which the mode was a source
constant no environment variable could touch. That guarantee was genuinely
stronger and genuinely unusable for anyone installing from PyPI, since it made
production access mean editing a file inside `site-packages`. The replacement is
narrower but honest: a safe default, exactly one variable that moves it, a hard
error on a typo, and a loud banner naming the mode and its source on every
start.

## Startup is staged and deferred

Four stages that fail independently:

| stage | produces | fails on |
|---|---|---|
| A | mode, paths, env files | a malformed mode value |
| B | `Config` | missing credentials, bad host |
| C | `SpecIndex` | missing or corrupt spec |
| D | client, fixture tracker | needs B |

C depends on A but **not** on B, which is worth the plumbing: with no
credentials at all, the four spec-only tools still work, so an agent can explore
the API and tell the user exactly what to set instead of failing blank.

Tools are wrapped by `_guarded`, which catches `StartupError` and returns it as
data — `{"ok": false, "remedy": ...}` — rather than letting it surface as a
transport failure the model can only report as "the server is broken". The
wrapper is signature-transparent via `functools.wraps`; without that, FastMCP
sees `(*args, **kwargs)` and rejects every tool.

`main()` deliberately does not exit non-zero on a configuration failure. A
non-zero exit makes the MCP client mark the server dead, and the user never
reaches `buildium_health` to find out why.

## Credentials never leave Buildium's hosts

Auth is two static headers; there is no OAuth flow. File transfers use separate
clients with **no default headers**, because the signed URL names a third-party
storage host — sending the client secret to a host named by an API response
would leak it wherever that response pointed. Signed URLs are scheme-checked
before use.

The audit log records method, path, query, body, status and timing. Headers are
never in a record, and signed URLs are replaced by a placeholder.

## Pagination reports its own honesty

`get_all_pages` infers the end of a collection from a short page. When it hits
the record cap it issues a `limit=1` probe to determine whether the result is
*actually* truncated, so a partial answer is labelled rather than silently
wrong. Fixture exclusion is computed from server rows, not kept rows, so
filtering cannot corrupt the offsets.
