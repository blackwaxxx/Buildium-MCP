"""The startup banner.

A server that can modify live property records should say so before it does.
The banner prints in every mode — including sandbox — so that its *absence* is
itself a signal that something did not start the way you think it did.

Two rules shape the implementation:

  * stderr, never stdout. Under the stdio transport, stdout carries JSON-RPC;
    a stray line there corrupts the protocol.
  * render_banner is pure. The text can then be asserted on directly, which is
    how the "never leaks a secret" test stays honest.
"""

from __future__ import annotations

import logging
import sys

from .config import DeploymentMode
from .runtime import StartupStatus

LOGGER_NAME = "buildium_mcp"

_WIDTH = 68


def _line(label: str, value: object) -> str:
    return f" {label:<16}: {value}"


def render_banner(status: StartupStatus, *, version: str = "0.1.0") -> str:
    """Render the banner. Pure — no I/O, no globals."""
    rule = "=" * _WIDTH
    rows = [
        rule,
        f" buildium-mcp {version}",
        _line("DEPLOYMENT MODE", f"{status.mode.value}  (from {status.mode_source})"),
        _line("BASE URL", status.base_url or "<not configured>"),
        _line("WRITES", "ALLOWED" if status.writes_allowed else "blocked at transport"),
    ]

    if not status.writes_allowed:
        rows.append(_line(
            "FILE DOWNLOADS",
            "permitted" if status.download_requests_allowed
            else "blocked (set production-readonly-files to permit)",
        ))
    if status.writes_allowed:
        rows.append(_line("WRITE MODE", status.write_mode))

    rows.append(_line("AUDIT LOG", status.run_log or f"disabled — {status.log_dir_error}"))
    rows.append(_line("SPEC", status.spec_path))
    if status.operations is not None:
        rows.append(_line("OPERATIONS", status.operations))

    if not status.ok:
        rows.append("")
        rows.append(f" NOT READY ({status.stage}): {status.error}")
        if status.remedy:
            rows.append(f" FIX: {status.remedy}")
        rows.append(" The server is running so buildium_health can explain this.")

    if status.mode is DeploymentMode.PRODUCTION_WRITE:
        rows.append("")
        rows.append(" !!! THIS SERVER CAN MODIFY LIVE PRODUCTION RECORDS !!!")
    elif status.mode.is_production:
        rows.append("")
        rows.append(" WARNING: bound to live production data (reads only).")

    rows.append(rule)
    return "\n".join(rows)


def configure_logging() -> logging.Logger:
    """Attach a stderr handler. Called from main() only.

    Never at import: a library that reconfigures logging on import is a menace
    to whatever application imported it.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def emit_banner(status: StartupStatus) -> None:
    logger = configure_logging()
    text = render_banner(status)
    if status.mode is DeploymentMode.PRODUCTION_WRITE or not status.ok:
        logger.warning(text)
    else:
        logger.info(text)
