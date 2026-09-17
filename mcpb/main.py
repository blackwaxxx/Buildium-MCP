"""Entry point for the Claude Desktop extension bundle.

Claude Desktop runs this file with ``uv run --directory <bundle> server/main.py``
after provisioning Python and the dependencies listed in the bundle's
pyproject.toml. The package itself is not installed into that environment
(``[tool.uv] package = false``), so put the bundled source on the path and hand
off to the ordinary server entry point. Nothing else lives here on purpose: the
bundle must behave exactly like ``pip install buildium-mcp``.
"""

from __future__ import annotations

import sys
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUNDLE_ROOT / "src"))

from buildium_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
