"""Write guardrails.

Two modes:

  fixtures (default) — the unattended posture. Creates must carry the fixture
      prefix in their name field so test data is identifiable, and updates or
      deletes are permitted only against records this process created. An agent
      working alone cannot mutate or destroy pre-existing records.

      Most of Buildium's POST endpoints have no name field at all: a charge, a
      payment, a journal entry, a note, a check. 84 of the 119 in the spec
      once the nested search below is taken into account.
      There is nothing on those payloads that could carry the prefix, so the
      guarantee above cannot be made about them. Against the sandbox that is
      harmless and they are allowed, because the data is disposable. Against a
      production host they are refused, since the alternative is to create a
      live record this mode has promised to keep identifiable and cannot.

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

from .config import Config, is_download_request_path, request_permitted

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


# Buildium nests the people it creates: POST /v1/leases carries Tenants[] and
# Cosigners[], each with a FirstName, and each of those becomes a real person
# record. A top-level-only scan found no name on that payload at all and waved
# the whole lease through, tenants included. So the search descends.
#
# The caps keep an enormous or maliciously deep body from turning this into an
# unbounded traversal. Hitting one is reported, never silently treated as a
# clean payload — see _collect_names. Depth is set with room to spare: the
# deepest POST body in the spec that nests anything is /v1/bills/payments at 3,
# and a legitimate payload that read as unreadable would be refused against
# production for no reason.
_MAX_NAME_DEPTH = 6
_MAX_NAME_NODES = 512


def _collect_names(payload: Any) -> tuple[list[tuple[str, str]], bool]:
    """Every human-readable label in `payload`, as (field path, value) pairs.

    Returns ``(names, truncated)``. Breadth-first, so a record's own top-level
    label is reported before the labels of things nested inside it, and
    NAME_FIELDS order decides within a single node. Field paths read like
    'Tenants[0].FirstName' so a refusal can say which value to fix.

    ``truncated`` is True when a cap was hit and part of the payload was never
    examined. The caller must not read that as "no unprefixed names here": it
    means "unknown", and the guard fails closed on it. Without that, burying a
    name past the node cap would be a way to walk an unprefixed record straight
    through the check.
    """
    found: list[tuple[str, str]] = []
    queue: list[tuple[str, Any, int]] = [("", payload, 0)]
    visited = 0
    truncated = False

    while queue:
        prefix, node, depth = queue.pop(0)
        visited += 1
        if visited > _MAX_NAME_NODES:
            truncated = True
            break

        if isinstance(node, dict):
            for key in NAME_FIELDS:
                value = node.get(key)
                if isinstance(value, str) and value:
                    found.append((f"{prefix}{key}", value))
            children = [
                (f"{prefix}{key}.", value)
                for key, value in node.items()
                if key not in NAME_FIELDS and isinstance(value, (dict, list))
            ]
        elif isinstance(node, list):
            # prefix ends in '.', so trimming it turns 'Tenants.' into
            # 'Tenants' before the index, giving 'Tenants[0].'.
            stem = prefix[:-1] if prefix.endswith(".") else prefix
            children = [
                (f"{stem}[{index}].", value)
                for index, value in enumerate(node)
                if isinstance(value, (dict, list))
            ]
        else:
            children = []

        if children and depth >= _MAX_NAME_DEPTH:
            truncated = True
        else:
            queue.extend((p, v, depth + 1) for p, v in children)

    return found, truncated


def _extract_name(payload: Any) -> str | None:
    """The single best label for `payload`, for the artifact log."""
    names, _ = _collect_names(payload)
    return names[0][1] if names else None


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
        # A download request is a POST that creates nothing. The read-only
        # modes return above; this is the same carve-out for the write-enabled
        # ones, which would otherwise refuse it below for having no name.
        if is_download_request_path(path):
            return

        # Every label on the payload, not just the top-level one: creating a
        # lease creates its tenants, and an unprefixed tenant is exactly the
        # untagged record this mode exists to prevent.
        names, truncated = _collect_names(body)
        for field_path, name in names:
            if not name.startswith(prefix):
                raise GuardViolation(
                    f"POST {path} refused in 'fixtures' mode: {field_path} is "
                    f"{name!r}, which must start with {prefix!r} so test data "
                    "stays identifiable and removable. Either prefix it, or "
                    "set BUILDIUM_WRITE_MODE=open to create real records."
                )

        # Either nothing on this payload can carry the prefix, or the payload
        # was too big to finish reading and an unprefixed name could be hiding
        # in the part that was skipped. Both mean the same thing: this mode
        # cannot promise the resulting record is identifiable.
        #
        # Whether that is acceptable depends on where the record would land,
        # not on which mode was asked for. Pointing a production-mode server at
        # the sandbox is still the sandbox, and the data is still disposable.
        if (truncated or not names) and not tracker.config.is_sandbox:
            why = (
                "it is too large or deeply nested to check in full"
                if truncated
                else f"it has no name field that could carry the {prefix!r} prefix"
            )
            raise GuardViolation(
                f"POST {path} refused in 'fixtures' mode: {why}, so the record "
                "it creates could not be guaranteed identifiable as test data "
                "or findable again for cleanup. Most Buildium write endpoints "
                "have no name field at all: charges, payments, journal entries, "
                "checks, notes. Against the sandbox those are allowed because "
                "the data is disposable, but this server is pointed at "
                f"{tracker.config.host}. Set BUILDIUM_WRITE_MODE=open to create "
                "live records deliberately, and expect to clean up by hand."
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
