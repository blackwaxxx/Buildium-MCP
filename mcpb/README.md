# Claude Desktop extension

This directory builds `buildium-mcp-<version>.mcpb`, a one-click install for
Claude Desktop. The user double-clicks the file, Claude Desktop shows a settings
form asking for their Buildium Client ID and Secret, and the server is ready.
No Python to install, no config file to edit.

It works because the bundle uses the `uv` server type: Claude Desktop keeps its
own copy of [uv](https://docs.astral.sh/uv/), runs `uv sync` against the
bundle's `pyproject.toml` at install time — downloading a Python if the machine
has none — and launches the server with `uv run`. The bundle itself is just the
package source, the dependency list, a five-line entry script and an icon.

## Build

```bash
.venv/bin/python mcpb/build.py          # -> dist/buildium-mcp-<version>.mcpb
.venv/bin/python mcpb/smoke.py          # installs dist/*.mcpb into a temp dir and runs it like Claude Desktop
.venv/bin/python mcpb/smoke.py --with-env   # same, forwarding your BUILDIUM_* credentials
```

`build.py` needs Node for `npx @anthropic-ai/mcpb pack`, and uv on PATH to write
a lockfile (optional). `manifest.json` and the bundle's `pyproject.toml` are
generated from the project's `pyproject.toml` and the live tool list, so they
cannot drift from the code; `tests/test_mcpb.py` pins the parts that matter.

## Files

| | |
|---|---|
| `build.py` | stages `build/mcpb/` and packs it |
| `main.py` | becomes `server/main.py` in the bundle: puts `src/` on the path and calls `buildium_mcp.server.main` |
| `smoke.py` | unpacks the packed bundle outside the repo, then `uv sync` + `uv run` + MCP handshake |
| `make_icon.py` | drew `icon.png`; committed so builds do not need Pillow |

## Settings form

| Field | Environment variable | Default |
|---|---|---|
| Buildium Client ID | `BUILDIUM_CLIENT_ID` | required |
| Buildium Client Secret | `BUILDIUM_CLIENT_SECRET` | required |
| Deployment mode | `BUILDIUM_DEPLOYMENT_MODE` | `sandbox` |
| Base URL | `BUILDIUM_BASE_URL` | `https://apisandbox.buildium.com` |
| Write mode | `BUILDIUM_WRITE_MODE` | `fixtures` |

The two secrets are marked `sensitive`, so Claude Desktop masks them and stores
them in its secure store rather than in a plain file. Every default is the same
safe posture a `pip install` starts in.

## The bundle is unsigned, on purpose

Claude Desktop shows the bundle as **unsigned** in the install dialog. That is
expected and installation still works. The reasoning:

- Claude Desktop only reports a signature when the operating system trusts the
  certificate chain for code signing (`security verify-cert -p codeSign` on
  macOS, the certificate store on Windows). A self-signed certificate fails that
  check, so a self-signed bundle is displayed as unsigned too — `mcpb sign
  --self-signed` changes nothing a user can see.
- A certificate the OS *does* trust is a code-signing certificate from a public
  CA. Since 2023 those are issued only with the private key on a hardware token
  or in the CA's cloud signer, and `mcpb sign` needs the key as a PEM file. The
  two do not currently fit together.

Sign only if a customer's Claude Desktop policy requires it (`signature required`
blocks anything but a CA-trusted signature), and expect to build a hardware-token
signing step for that. Never commit a private key; `.gitignore` excludes `*.pem`.
