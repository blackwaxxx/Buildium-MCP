# Changelog

## Unreleased

### Security
- A `.env` file now supplies only `BUILDIUM_*` variables. Everything else in
  it used to be imported too, and httpx honours `HTTPS_PROXY` and
  `SSL_CERT_FILE`, so a `.env` setting both could route the request carrying
  the client secret through a proxy that could read it.
- The working directory is no longer searched for a `.env`. MCP clients start
  the server wherever they like (Claude Code uses the open project), so that
  search read other projects' files and ranked them above your own
  configuration. A checkout's own `.env` is still found.
- Installing into another project's virtualenv no longer makes that project's
  `.env` look like this checkout's.
- A blank `BUILDIUM_FIXTURE_PREFIX` falls back to the default. Every name
  starts with an empty string, so a blank prefix turned the fixtures-mode name
  check off, and the guard now refuses outright if it ever sees one.
- `fixtures` mode checks every name in a create payload, nested ones included
  (a lease's `Tenants[].FirstName`), and refuses creates with no name field
  against production.

### Fixed
- `buildium_lease_roster` read one page of tenants (100) and said nothing, so
  any larger portfolio was undercounted and a `lease_id` whose tenants sat past
  that page returned an empty roster. It now follows every page up to 1000 and
  reports `complete`; `limit` is the page size.
- A `Retry-After` header in HTTP-date form raised `ValueError` out of the tool.
- A failure while building the HTTP client (for example a stale
  `SSL_CERT_FILE`) crashed every tool, `buildium_health` included. It is now a
  startup error with a remedy, like a missing key.

### Changed
- The README installs from GitHub. The package is not on PyPI yet, and
  `pip install buildium-mcp` would install whatever someone else publishes
  under that name.

## 0.1.1 — 2026-09-18

### Changed
- Claude Desktop extension: the deployment mode is now three on/off toggles
  ("Connect to production", "Allow changes in production", "Allow file
  downloads in production") plus one for the write mode, instead of free-text
  fields. The form has no dropdown, and typing `production-readonly-files` is
  not a reasonable ask. The bundle's launcher translates the toggles into the
  same two variables the server has always read; the server is unchanged.
- The version string has one source (`buildium_mcp.__version__`); the banner
  and the User-Agent header read it.

### Fixed
- The extension launcher cleared its environment before reading it, so the
  credentials from the settings form were discarded. Caught by the bundle
  smoke test.

## 0.1.0 — 2026-09-17

First public release.

### Added
- A Claude Desktop extension bundle (`.mcpb`, built by `mcpb/build.py`). Uses
  the `uv` runtime, so Claude Desktop provisions Python and dependencies
  itself and asks for the Buildium keys in a settings form. Ships unsigned;
  see KNOWN-LIMITATIONS.md for why.
- `BUILDIUM_DEPLOYMENT_MODE` selects the deployment mode. Previously this was a
  source constant, which a `pip install` user could only change by editing a
  file inside `site-packages`.
- `production-readonly-files`: a read-only mode that permits Buildium's seven
  file-download endpoints and nothing else. Buildium models a download as a
  POST, so strict read-only cannot fetch a lease PDF.
- Startup is deferred and staged. A missing API key no longer kills the process
  at import; `buildium_health` reports what is missing and how to fix it, and
  the four spec-only tools keep working without credentials.
- A startup banner on stderr naming the active mode and where it came from.
- `tests/conftest.py` isolates the offline suite from any `.env` on the machine.

### Changed
- The OpenAPI spec ships inside the package, so one code path serves both a
  wheel and an editable checkout.
- `.env` and the audit logs resolve to platform config/state directories
  instead of a repo root. Overridable per-file.
- `DeploymentMode.writes_allowed` and `.is_production` are allowlists rather
  than denylists, so a new mode is powerless until explicitly named.
- An unwritable log directory now degrades visibly — `buildium_health` reports
  the reason — instead of silently swallowing every `OSError` at the write site.

### Fixed
- `buildium_download_file` and `buildium_upload_file` accepted any request path.
  In `sandbox` and `production-write` mode that made the read-only-annotated
  download tool an arbitrary empty-body `POST`, and the upload tool an arbitrary
  `POST` with a metadata body, bypassing the spec lookup and the fixture
  tracker. Both helpers are now confined to Buildium's seven download / seven
  upload endpoints in every mode.
- The read-only transport guard refused `POST`/`PUT`/`PATCH`/`DELETE` and let
  every other verb through. It now allows only `GET`, `HEAD` and `OPTIONS`, and
  checks host and scheme for every request rather than only for writes.
- README claimed 43 resource areas; the spec declares 42.
- README and COVERAGE.md claimed all 238 GET operations executed. 208 were
  sent and 178 verified; the rest are `needs-setup` for want of a record id.
