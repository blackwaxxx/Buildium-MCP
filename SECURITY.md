# Security Policy

This server holds credentials for a property-management system: tenant names
and contact details, lease terms, bank accounts, and financial ledgers. Please
treat findings here as you would for any system holding personal and financial
records.

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub's
[Security Advisories](https://github.com/blackwaxxx/Buildium-MCP/security/advisories/new)
so a fix can ship before details are public.

Please include the deployment mode, the version, and a reproduction if you have
one. Expect an acknowledgement within a few days.

## What is in scope

- Any way to make a mutating request from `production-readonly` or
  `production-readonly-files`, including reaching past `BuildiumClient`.
- Any path that widens the download carve-out beyond the seven endpoints in
  `DOWNLOAD_REQUEST_PATHS`, or aims one at a host outside the allowlist.
- Any way to make `buildium_download_file` or `buildium_upload_file` send a
  request to an endpoint outside `DOWNLOAD_REQUEST_PATHS` /
  `UPLOAD_REQUEST_PATHS`, in any mode.
- Any way to reach a production host without both `BUILDIUM_DEPLOYMENT_MODE`
  and a production `BUILDIUM_BASE_URL`.
- Credentials appearing in `run.log`, in tool output, in the startup banner, or
  in any request to a non-Buildium host.
- A `fixtures`-mode write that modifies a record the process did not create.

## What is not

- `production-write` doing what it says. It is documented as unguarded; the
  protection there is `BUILDIUM_WRITE_MODE=fixtures`, which is the default.
- Vulnerabilities in the Buildium API itself — report those to Buildium.
- The bundled OpenAPI document being out of date. Use `BUILDIUM_SPEC_PATH`.

## Known design limits

These are deliberate, documented, and not vulnerabilities on their own. See
[KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md) for the reasoning.

- Fixture-name enforcement inspects five name-like fields; a POST body carrying
  none of them is not prefix-checked.
- The "records created this session" set is in memory only and is empty after a
  restart.
- `run.log` records request bodies, which for writes include record data.
- `buildium_upload_file` reads any local file the server process can read, and
  `buildium_download_file` writes to any local path it can write. The MCP client
  decides who may call them.
