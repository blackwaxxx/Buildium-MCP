"""Entry point for the Claude Desktop extension bundle.

Claude Desktop runs this file with ``uv run --directory <bundle> server/main.py``
after provisioning Python and the dependencies listed in the bundle's
pyproject.toml. The package itself is not installed into that environment
(``[tool.uv] package = false``), so this puts the bundled source on the path
and hands off to the ordinary server entry point.

It also does one translation. Claude Desktop's settings form has no dropdown,
only on/off toggles, and asking someone to type ``production-readonly-files``
into a text box is not "easy". So the form offers three toggles, which this
file turns into the two environment variables the server actually reads:

    Connect to production          off -> sandbox, sandbox URL
                                   on  -> production URL, and then:
    Allow changes in production      off -> production-readonly
    Allow file downloads             off/on -> ...-readonly / ...-readonly-files
                                   (writes on -> production-write, downloads implied)

Reaching production writes therefore still takes two deliberate switches. The
server's own rule — exactly one variable selects the mode, and a production
host is refused unless that variable permits it — is untouched; this launcher
merely sets those variables before the server starts, and the server's normal
checks run afterwards as they would for any other client.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[1]

# Toggle names as they arrive from the manifest's mcp_config.env.
PRODUCTION = "BUILDIUM_MCPB_PRODUCTION"
ALLOW_WRITES = "BUILDIUM_MCPB_ALLOW_WRITES"
ALLOW_DOWNLOADS = "BUILDIUM_MCPB_ALLOW_DOWNLOADS"
OPEN_WRITE_MODE = "BUILDIUM_MCPB_OPEN_WRITE_MODE"

SANDBOX_URL = "https://apisandbox.buildium.com"
PRODUCTION_URL = "https://api.buildium.com"


def _on(value: str | None) -> bool:
    """Claude Desktop substitutes a boolean toggle as text; be strict about it."""
    return (value or "").strip().lower() in ("true", "1", "yes", "on")


def translate(env: dict[str, str]) -> dict[str, str]:
    """Turn the form's toggles into the server's configuration variables.

    Pure, so it can be tested without launching anything. Every toggle is off
    when absent, so an empty form means the sandbox, exactly as ``pip install``
    with no variables does.
    """
    out = dict(env)
    production = _on(env.get(PRODUCTION))
    writes = _on(env.get(ALLOW_WRITES))
    downloads = _on(env.get(ALLOW_DOWNLOADS))

    if not production:
        mode, url = "sandbox", SANDBOX_URL
    elif writes:
        mode, url = "production-write", PRODUCTION_URL
    elif downloads:
        mode, url = "production-readonly-files", PRODUCTION_URL
    else:
        mode, url = "production-readonly", PRODUCTION_URL

    out["BUILDIUM_DEPLOYMENT_MODE"] = mode
    out["BUILDIUM_BASE_URL"] = url
    out["BUILDIUM_WRITE_MODE"] = "open" if _on(env.get(OPEN_WRITE_MODE)) else "fixtures"
    for key in (PRODUCTION, ALLOW_WRITES, ALLOW_DOWNLOADS, OPEN_WRITE_MODE):
        out.pop(key, None)
    return out


def apply(environ) -> None:
    """Rewrite a live environment mapping in place with translate()'s result.

    Separate from main() so a test can run it against a plain dict. The first
    version cleared os.environ *before* snapshotting it, which silently threw
    the credentials away; the smoke test caught it, this keeps it caught.
    """
    translated = translate(dict(environ))
    for key in set(environ) - set(translated):
        del environ[key]
    environ.update(translated)


def main() -> None:
    apply(os.environ)
    sys.path.insert(0, str(BUNDLE_ROOT / "src"))
    from buildium_mcp.server import main as serve

    serve()


if __name__ == "__main__":
    main()
