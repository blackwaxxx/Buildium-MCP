# Changelog

## 0.1.0 — unreleased

First public release.

### Added
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
- README claimed 43 resource areas; the spec declares 42.
- README and COVERAGE.md claimed all 238 GET operations executed. 208 were
  sent and 178 verified; the rest are `needs-setup` for want of a record id.
