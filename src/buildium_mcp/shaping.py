"""Pure response-shaping helpers.

Kept separate from server.py, which loads credentials at import time and so
cannot be imported by an offline test.
"""

from __future__ import annotations

from typing import Any


def project(data: Any, fields: list[str] | None) -> Any:
    """Narrow records to the requested top-level fields.

    Buildium returns fat objects — an owner record carries tax IDs, fax numbers
    and mailing addresses even when the caller only wanted PropertyIds. Left
    unfiltered that burns context and needlessly surfaces PII.
    """
    if not fields:
        return data
    keep = set(fields)

    def pick(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: v for k, v in obj.items() if k in keep}
        return obj

    if isinstance(data, list):
        return [pick(item) for item in data]
    return pick(data)


# The fields Buildium uses for a record's human-readable label. Kept in step
# with guards.NAME_FIELDS: the same field that makes a create identifiable as a
# fixture is the one that identifies it on the way back out.
NAME_FIELDS = ("Name", "Title", "Subject", "CategoryName", "CompanyName",
               "FirstName", "UnitNumber", "Memo")


def is_fixture(record: Any, prefix: str) -> bool:
    """Whether a record was created by test tooling rather than by real use.

    Test fixtures cannot be deleted from most Buildium collections — only 14 of
    462 operations support DELETE — so any sandbox that has been exercised
    accumulates them permanently. That makes every count ambiguous unless the
    ambiguity is surfaced: a model asked "how many leases have co-tenants" has
    no way to know some of the answer is test data unless something says so.
    """
    if not isinstance(record, dict) or not prefix:
        return False
    for key in NAME_FIELDS:
        value = record.get(key)
        if isinstance(value, str) and value.startswith(prefix):
            return True
    return False


def split_fixtures(records: list[Any], prefix: str) -> tuple[list[Any], list[Any]]:
    """Partition into (real, fixture)."""
    real, fixtures = [], []
    for record in records:
        (fixtures if is_fixture(record, prefix) else real).append(record)
    return real, fixtures


def list_result(
    data: Any, limit: int, offset: int, fields: list[str] | None = None,
    fixture_prefix: str = "", exclude_fixtures: bool = False,
) -> dict[str, Any]:
    """Wrap a list response with pagination metadata.

    Buildium returns no total count, so `has_more` is inferred: a full page
    implies there may be another. It is a hint, not a guarantee — a collection
    whose size is an exact multiple of `limit` reports has_more on its last page.
    """
    items = data if isinstance(data, list) else [data]
    full_page = len(items) == limit
    real, fixtures = split_fixtures(items, fixture_prefix)
    kept = real if exclude_fixtures else items

    out: dict[str, Any] = {
        "ok": True,
        "count": len(kept),
        "limit": limit,
        "offset": offset,
        "has_more": full_page,
        "next_offset": offset + len(items) if full_page else None,
        "data": project(kept, fields),
    }
    # Only mentioned when there is something to mention, so the common case
    # stays uncluttered.
    if fixtures:
        out["fixture_count"] = len(fixtures)
        out["fixtures_excluded"] = exclude_fixtures
        if not exclude_fixtures:
            out["fixture_note"] = (
                f"{len(fixtures)} of these {len(items)} records are test "
                f"fixtures (name starts with {fixture_prefix!r}). They are real "
                "records in this account and most cannot be deleted. Pass "
                "exclude_fixtures=true to count only genuine data."
            )
    return out
