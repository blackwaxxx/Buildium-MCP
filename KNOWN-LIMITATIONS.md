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

In `fixtures` mode a created record's name must start with the fixture prefix.
The name is read from the first non-empty of `Name`, `Title`, `Subject`,
`CategoryName`, `FirstName`.

**A POST body carrying none of those fields is not prefix-checked.** That covers
most financial posts — journal entries, bill payments, deposits — which have no
natural name field. Fixtures mode is a guard against *accidental* damage, not an
authorization system. For real work in production use `production-write` with
`BUILDIUM_WRITE_MODE=open` and mean it.

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

`buildium_upload_file` reads whatever local path it is given, and
`buildium_download_file` writes wherever it is told to. That is what they are
for, but it means a client that grants them is granting file access on the
machine the server runs on. Both are confined to Buildium's file endpoints on
the network side; there is no equivalent confinement on the local side.

## Sandbox records cannot be cleaned up

Buildium offers `DELETE` on only 14 of its 462 operations, so a sandbox
accumulates test records permanently. That is why `exclude_fixtures` exists on
every list tool, and why list responses report `fixture_count` when any are
present — a count is never silently wrong, but it may need the flag.

## The audit log grows without bound

`run.log` gets one JSON line per request and is never rotated. It records
request bodies, which for writes include record data — tenant names, amounts.
It does **not** record credentials. Set `BUILDIUM_RUN_LOG=off` if that is not
the trade you want.

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
