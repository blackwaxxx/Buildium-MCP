"""Write guardrails.

Two modes:

  fixtures (default) — the unattended posture. Creates must carry the fixture
      prefix in their name field so test data is identifiable, and updates or
      deletes are permitted only against records this process created. An agent
      working alone cannot mutate or destroy pre-existing records.

  open — normal operation for when a human is present. All writes are allowed,
      but deletes still require an explicit confirm flag, and everything is
      audited either way.

Mode is read from BUILDIUM_WRITE_MODE and defaults to fixtures.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import Config, request_permitted

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DESTRUCTIVE_METHODS = frozenset({"DELETE"})

# Field names Buildium uses for the human-readable label on a record.
NAME_FIELDS = ("Name", "Title", "Subject", "CategoryName", "FirstName")


class GuardViolation(RuntimeError):
    """A write was refused by policy. Not an API error — we never sent it."""


@dataclass
class FixtureTracker:
    """Records created during this process's lifetime."""

    config: Config
    created: dict[str, set[str]] = field(default_factory=dict)

    def _collection(self, path: str) -> str:
        """Normalize '/v1/vendors/123' and '/v1/vendors' to the same collection."""
        parts = [p for p in path.strip("/").split("/") if p]
        if parts and parts[-1].isdigit():
            parts = parts[:-1]
        return "/" + "/".join(parts)

    def record(self, path: str, record_id: Any, payload: Any = None) -> None:
        if record_id is None:
            return
        coll = self._collection(path)
        self.created.setdefault(coll, set()).add(str(record_id))
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "collection": coll,
            "id": str(record_id),
            "name": _extract_name(payload),
        }
        if self.config.artifact_log is None:
            return
        try:
            with self.config.artifact_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def owns(self, path: str) -> bool:
        parts = [p for p in path.strip("/").split("/") if p]
        if not parts or not parts[-1].isdigit():
            return False
        return parts[-1] in self.created.get(self._collection(path), set())

    def summary(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sorted(self.created.items())}


def _extract_name(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in NAME_FIELDS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def write_mode() -> str:
    mode = os.getenv("BUILDIUM_WRITE_MODE", "fixtures").strip().lower()
    return mode if mode in ("fixtures", "open") else "fixtures"


def check_write(
    method: str,
    path: str,
    body: Any,
    tracker: FixtureTracker,
    *,
    confirm: bool = False,
) -> None:
    """Raise GuardViolation if this write is not permitted. Returns None if OK."""
    method = method.upper()
    if method not in WRITE_METHODS:
        return

    # Deployment mode outranks write mode. In the read-only modes this refusal
    # is belt-and-braces: client.py blocks the same call at the transport layer
    # even if this check were removed.
    if not tracker.config.writes_allowed:
        if not request_permitted(tracker.config.mode, method, path):
            raise GuardViolation(
                f"{method} {path} refused: BUILDIUM_DEPLOYMENT_MODE is "
                f"{tracker.config.mode.value!r}, which permits reads only."
            )
        # A permitted file-download POST is not a "write" for fixture purposes.
        # Returning early matters: otherwise it falls through to the name-prefix
        # check below and gets refused for lacking a ZZ-MCPTEST- title.
        return

    mode = write_mode()

    if method in DESTRUCTIVE_METHODS and not confirm:
        raise GuardViolation(
            f"DELETE {path} refused: destructive calls require confirm=true. "
            "Re-issue the call with confirm set once you are certain."
        )

    if mode == "open":
        return

    prefix = tracker.config.fixture_prefix

    if method == "POST":
        name = _extract_name(body)
        if name is not None and not name.startswith(prefix):
            raise GuardViolation(
                f"POST {path} refused in 'fixtures' mode: the record's name "
                f"{name!r} must start with {prefix!r} so test data stays "
                "identifiable and removable. Either prefix the name, or set "
                "BUILDIUM_WRITE_MODE=open to create real records."
            )
        return

    # PUT / PATCH / DELETE must target something we created this run.
    if not tracker.owns(path):
        raise GuardViolation(
            f"{method} {path} refused in 'fixtures' mode: this process did not "
            "create that record, so it will not modify or delete it. Records "
            "created earlier in this run are listed by buildium_created_fixtures. "
            "Set BUILDIUM_WRITE_MODE=open to operate on pre-existing records."
        )
