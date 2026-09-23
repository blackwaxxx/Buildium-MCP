# Known limitations

Deliberate trade-offs, written down so they read as decisions rather than
oversights. Each says what the limit is, why it exists, and what to do about it.

## File downloads need a mode that permits them

Buildium issues a file download by **POSTing** for a short-lived signed URL. A
server that refuses every POST therefore cannot fetch a lease PDF, an invoice
scan, or a unit photo.

`production-readonly` keeps that guarantee absolute. If you need files from
production, use `production-readonly-files`, which exempts exactly seven
operations — the `downloadrequest` / `downloadrequests` endpoints — and still
refuses everything else in the transport.

The exemption is deliberately narrow: an anchored pattern matched against the
raw, still-percent-encoded wire path, with the host checked as well. A test
iterates every POST in the spec and asserts precisely those seven are reachable.

## Fixture-mode name checking is a heuristic

In `fixtures` mode every name in a create payload must start with the fixture
prefix, at any depth: a lease's `Tenants[0].FirstName` is checked the same way
as its own `Name`. A "name" is one of five fields — `Name`, `Title`, `Subject`,
`CategoryName`, `FirstName` — so a value in any other field (`LastName`,
`CompanyName`, a memo) is neither checked nor enough to make a record
identifiable.

A create with none of those fields anywhere covers most financial posts:
charges, payments, journal entries, checks. It is allowed against the sandbox
and refused against production, because nothing on it could carry the prefix.
The same goes for a payload too large or too deeply nested to scan in full. A
blank `BUILDIUM_FIXTURE_PREFIX` falls back to the default rather than matching
every name.

A create under an existing record — `POST /v1/leases/{leaseId}/renewals`, a
charge or a note on a lease — changes that record, so off the sandbox every
record named in the path must be one this process created, as for an update.
In the sandbox it may be any record, because the data is disposable.

**What the mode does not check is a record the payload names.** A new lease
carries the `UnitId` of an existing unit; an upload to `/v1/files/uploads`
carries the `EntityId` it attaches to. Those references are everywhere in
Buildium's write bodies (units, properties, GL accounts, vendors), and most
point at records no test would ever create, so they are not checked. In
production, a prefixed lease can therefore be created on a real unit, and a
prefixed file attached to a real record. Fixtures mode is a guard against
*accidental* damage, not an authorization system. For real work in production
use `production-write` with `BUILDIUM_WRITE_MODE=open` and mean it.

## `all_pages` returns at most 1000 records, `count_only` counts to 100,000

The list tools and `buildium_call_endpoint` stop following pages at 1000
records, and report `complete: false` when more remained. The limit is about the
size of the answer, not the API: a lease record is about 1.6 KB and a tenant
about 2.5 KB, so a thousand full records is already far more than an MCP client
accepts as one tool result.

Counting is not affected: `count_only=true` follows every page, up to 100,000
records, and returns only the number. What the cap does limit is anything that
needs the records themselves — a rent total, say — past 1000 of them. That needs
a narrower query (the tools' filters, and `fields` to trim each record) or
manual paging with `limit` (up to 1000) and `offset`. There is no server-side
sum or grouping.

`buildium_lease_roster` is not bound by the cap either, because it returns a
compact join rather than the records. It reads up to 100,000 tenants, reads only one unit
when given a lease, and above 300 leases returns counts instead of the
tenant-by-tenant listing.

## "Created this session" is in memory only

`fixtures` mode will only update or delete records the current process created.
That set lives in memory. After a restart it is empty, so a record created in an
earlier run can no longer be modified — the IDs are in `created-records.log`, but
nothing reads that file back. Use `BUILDIUM_WRITE_MODE=open` to operate on
pre-existing records.

Uploaded files are a related gap: Buildium creates the file record
asynchronously after the signed-URL PUT, so it never lands in the tracker. That
finalization runs on Buildium's schedule, not the caller's — in the sandbox it
has taken 2–5 seconds on most runs and over four minutes on others. A tool call
that uploads and then immediately lists files may not see the new record.

## The file tools touch the local filesystem

`buildium_download_file` writes only inside one folder, `~/Downloads/Buildium`
unless `BUILDIUM_DOWNLOAD_DIR` moves it. Paths outside it are refused, symlinks
are resolved before the check, and an existing file is replaced only with
`overwrite=true`. That confinement is structural.

`buildium_upload_file` is not confined the same way, because uploading a file
from wherever it lives is the point of the tool. It refuses the places
credentials live: hidden files and folders (`~/.ssh`, `~/.aws`, any `.env`),
files named `*.env`, and this server's own configuration and log folders. That
is a denylist, so it narrows the risk rather than closing it: a secret in an
ordinary file in `~/Documents` can still be uploaded. Both tools are confined
to Buildium's file endpoints on the network side, and the MCP client decides who
may call them.

## Sandbox records cannot be cleaned up

Buildium offers `DELETE` on only 14 of its 462 operations, so a sandbox
accumulates test records permanently. That is why `exclude_fixtures` exists on
every list tool, and why list responses report `fixture_count` when any are
present — a count is never silently wrong, but it may need the flag.

## The audit log grows without bound

`run.log` gets one JSON line per request and is never rotated. It records
request bodies, which for writes include record data — tenant names, amounts.
It does **not** record credentials. It is created readable by its owner only,
and a log left readable by an older version is tightened on the next write.
Set `BUILDIUM_RUN_LOG=off` if that is not the trade you want.

## Coverage is uneven between reads and writes

218 of 462 operations are verified: 178 GETs and 40 writes. The uncovered GETs
are `needs-setup` — the sandbox holds no record of the required type, so there
is no id to call them with. The 184 unattempted writes are deliberate: the
sandbox cannot be reset, so writes prove one representative round trip per
entity family rather than every operation. COVERAGE.md states a reason per row.

## The bundled spec is a snapshot

`src/buildium_mcp/specs/buildium-openapi.json` is pinned at release time. Buildium
ships changes faster than this package does. Point `BUILDIUM_SPEC_PATH` at a
fresher copy if you need one; the index is built generically from `paths` and
`components.schemas`.

Two pieces of the code are tuned to this document's conventions and may need
attention with a much newer spec: the deprecation-notice parser expects
Buildium's literal `410 Gone` prose, and `KNOWN_REQUIRED_HINTS` in `client.py`
hard-codes four `/v1/...` paths.

## Rate limiting is minimal

Only HTTP 429 is retried, at most twice, honouring `Retry-After`. There is no
exponential backoff, no jitter, no retry on 5xx or connection errors, and no
client-side rate limiter. For bulk work, pace the calls yourself.

## The Claude Desktop bundle is unsigned

Claude Desktop reports a signature only when the operating system trusts the
signing certificate for code signing. A self-signed certificate does not pass
that check, so self-signing would display exactly as unsigned; and the
publicly trusted certificates that would pass are issued with hardware-held
keys the `mcpb sign` tool cannot use. The bundle therefore ships unsigned, and
the install dialog says so. Organisations that enforce Claude Desktop's
"signature required" policy cannot install it until that changes. Details in
[mcpb/README.md](mcpb/README.md).

## The eval suite is not portable

`evals/buildium_eval.xml` and its answer key were derived from one Buildium
sandbox's seed data. The questions are reusable; the answers are not. Treat them
as an illustration of the evaluation method, not a suite you can run.
