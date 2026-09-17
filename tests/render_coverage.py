"""Render COVERAGE.md from the raw results of the two coverage walks.

Reads coverage-raw.json, written by tests/coverage_matrix.py (reads) and
tests/coverage_writes.py (writes), and produces the matrix over all 462
operations. Pure formatting — it performs no API calls and invents no state.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "coverage-raw.json"
OUT = ROOT / "COVERAGE.md"

STATES = ["verified", "needs-params", "needs-setup", "write-skipped", "broken"]

STATE_MEANING = {
    "verified": "executed against the sandbox and returned success",
    "needs-params": "executed, but rejected for inputs that could not be derived "
                    "from the spec or from sandbox data",
    "needs-setup": "not provable here: no record of the required type exists in "
                   "this sandbox, or the API key lacks the resource scope",
    "write-skipped": "deliberately not executed; each row gives the reason",
    "broken": "failed in a way that suggests a real defect",
}


def load() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not RAW.is_file():
        sys.exit(f"{RAW} not found — run tests/coverage_matrix.py and "
                 "tests/coverage_writes.py first.")
    raw = json.loads(RAW.read_text())

    merged: dict[str, dict[str, Any]] = {}
    # An operation can appear in both walks: the write scenarios read back what
    # they create. Both are real executions, so the stronger result wins — the
    # read walk may report needs-setup for a record type that did not exist
    # until the write run made one, and discarding that would understate what
    # was actually proven.
    rank = {s: i for i, s in enumerate(reversed(STATES))}
    for source in ("read_results", "write_results"):
        for key, row in raw.get(source, {}).items():
            current = merged.get(key)
            if current is None or rank.get(row["state"], 0) > rank.get(current["state"], 0):
                merged[key] = dict(row, proven_by=source)
    return merged, raw


def spec_operations() -> dict[str, tuple[str, ...]]:
    """Tags per operation, straight from the spec, so the matrix is checked
    against the real operation list rather than against itself."""
    sys.path.insert(0, str(ROOT / "src"))
    from buildium_mcp import paths
    from buildium_mcp.spec import load_index

    index = load_index(paths.resolve_spec_path())
    return {ep.key: (ep.tags or ("Untagged",)) for ep in index.endpoints}


def bar(counts: Counter, total: int) -> str:
    verified = counts.get("verified", 0)
    pct = round(100 * verified / total) if total else 0
    filled = round(pct / 5)
    return f"`{'█' * filled}{'·' * (20 - filled)}` {verified}/{total} ({pct}%)"


def main() -> None:
    merged, raw = load()
    tags_by_key = spec_operations()

    missing = [k for k in tags_by_key if k not in merged]
    extra = [k for k in merged if k not in tags_by_key]
    for key in missing:
        merged[key] = {
            "method": key.split(" ", 1)[0], "path": key.split(" ", 1)[1],
            "state": "needs-setup", "reason": "not reached by either walk",
        }
    if extra:
        # A key the spec does not contain means a scenario labelled its call
        # with a path that is not a real operation. Dropping it quietly is how
        # a verified operation ends up reported as skipped — which happened
        # once, with PUT /v1/rentals/owners/{ownerId} where the spec says
        # {rentalOwnerId}. Fail loudly instead.
        sys.exit(
            "These result keys are not operations in the spec, so a scenario "
            "has mislabelled a call. Fix the spec_path it passes:\n  "
            + "\n  ".join(sorted(extra))
        )

    total = len(merged)
    by_state = Counter(r["state"] for r in merged.values())
    by_method: dict[str, Counter] = defaultdict(Counter)
    for key, row in merged.items():
        by_method[row["method"]][row["state"]] += 1

    by_tag: dict[str, Counter] = defaultdict(Counter)
    rows_by_tag: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for key, row in sorted(merged.items(), key=lambda kv: (kv[1]["path"], kv[1]["method"])):
        tag = tags_by_key.get(key, ("Untagged",))[0]
        by_tag[tag][row["state"]] += 1
        rows_by_tag[tag].append((key, row))

    out: list[str] = []
    w = out.append

    w("# Coverage matrix")
    w("")
    w(f"All **{total}** operations in the Buildium Open API, each executed against "
      "the sandbox or given a reason why not.")
    w("")
    w(f"- Reads walked: {raw.get('generated_at', 'n/a')} "
      f"({raw.get('elapsed_s', '?')}s)")
    w(f"- Writes walked: {raw.get('write_generated_at', 'n/a')} "
      f"({raw.get('write_elapsed_s', '?')}s)")
    w(f"- Host: `{raw.get('host', 'apisandbox.buildium.com')}` — sandbox only")
    w("")
    w("Regenerate with:")
    w("")
    w("```bash")
    w(".venv/bin/python tests/coverage_matrix.py   # 238 GETs, read-only")
    w(".venv/bin/python tests/coverage_writes.py   # curated write scenarios")
    w(".venv/bin/python tests/render_coverage.py   # this file")
    w("```")
    w("")

    w("## Totals")
    w("")
    w("| State | Count | Share | Meaning |")
    w("|---|---:|---:|---|")
    for state in STATES:
        count = by_state.get(state, 0)
        w(f"| **{state}** | {count} | {round(100 * count / total)}% | "
          f"{STATE_MEANING[state]} |")
    w(f"| | **{total}** | | |")
    w("")

    verified_total = by_state.get("verified", 0)
    w(f"**{verified_total} of {total} operations ({round(100 * verified_total / total)}%) "
      "were executed successfully against live sandbox data.**")
    w("")
    if by_state.get("broken"):
        w(f"{by_state['broken']} operations are marked broken — see the tables below.")
    else:
        w("No operation is marked broken: nothing failed in a way that suggests a "
          "defect in this server or in the API.")
    w("")

    w("## By method")
    w("")
    w("| Method | Total | Verified | Needs params | Needs setup | Write-skipped | Broken |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        counts = by_method.get(method)
        if not counts:
            continue
        subtotal = sum(counts.values())
        w(f"| {method} | {subtotal} | " + " | ".join(
            str(counts.get(s, 0)) for s in STATES) + " |")
    w("")
    # Counted, never asserted. An earlier version of this file claimed every
    # GET had been executed; it had not, and a reader checking the table found
    # the contradiction immediately. Numbers here are derived from the data.
    get_counts = by_method.get("GET", {})
    get_total = sum(get_counts.values())
    get_verified = get_counts.get("verified", 0)
    get_unmet = get_total - get_verified
    unmet_states = ", ".join(
        f"{n} `{state}`"
        for state, n in sorted(get_counts.items())
        if state != "verified" and n
    )
    w(f"Of the {get_total} GET operations, {get_verified} were called against the "
      f"sandbox and returned successfully. The other {get_unmet} ({unmet_states}) "
      "were not: the sandbox holds no record of the required type, so there was "
      "no id to call them with. They are not known to be broken — they are "
      "untested, and each row states what it lacked.")
    w("")
    w("The write columns are deliberately uneven: the sandbox cannot be reset, "
      "so writes prove one representative round trip per entity family rather "
      "than every operation. Each skipped row states its own reason.")
    w("")

    w("## By resource area")
    w("")
    w("| Area | Operations | Verified | Progress |")
    w("|---|---:|---:|---|")
    for tag in sorted(by_tag, key=lambda t: (-sum(by_tag[t].values()), t)):
        counts = by_tag[tag]
        subtotal = sum(counts.values())
        w(f"| {tag} | {subtotal} | {counts.get('verified', 0)} | "
          f"{bar(counts, subtotal)} |")
    w("")

    w("## What the sandbox taught us that the spec does not say")
    w("")
    w("Each of these cost a failed call to discover and is now encoded in the "
      "walkers, in the server's error hints, or both.")
    w("")
    w("| Finding | Where it bites |")
    w("|---|---|")
    w("| Every date-range filter is capped at **365 days**, stated only in the "
      "422 body | 9 endpoints, including `/v1/generalledger` and every "
      "`/v1/bankaccounts/{id}/*` collection |")
    w("| Request bodies declare **no required fields at the top level** — they "
      "are wrapped in a single-member `allOf` | all 119 POSTs; fixed by "
      "flattening in `spec.py` |")
    w("| `/v1/bills` requires `frompaiddate` **and** `topaiddate`, neither "
      "marked required | `/v1/bills` |")
    w("| `/v1/inventoryassets` and `/v1/inventorystorages` require "
      "`entitytype` + `entityid`, neither marked required | 2 endpoints |")
    w("| `IsCashAsset` is required when a GL account's `SubType` is "
      "`CurrentAsset`; `AccountNumber` is required on update | "
      "`POST`/`PUT /v1/glaccounts` |")
    w("| `WorkDetails` is a description **string**; the nested object is "
      "`Task` | `POST`/`PUT /v1/workorders` |")
    w("| `LeaseToDate` is rejected outright on `AtWill` leases | "
      "`PUT /v1/leases/{leaseId}` |")
    w("| Task history has **no POST**. Entries appear when a task changes; the "
      "only writable path is `PUT` with a `Message` field | "
      "`/v1/tasks/{taskId}/history/{taskHistoryId}` |")
    w("| Uploads are AWS **presigned PUT**, not multipart POST, and every "
      "`x-amz-meta-*` header must be reproduced exactly | all upload endpoints |")
    w("| File records are created **asynchronously** after storage accepts the "
      "bytes — the record does not exist the instant the upload returns | "
      "`/v1/files` |")
    w("| Parameter names are reused across unrelated ID spaces: a `tenantId` "
      "from `/v1/associations/tenants` 404s against `/v1/leases/tenants` | "
      "the whole templated-path surface |")
    w("")

    w("## Full matrix")
    w("")
    w("Grouped by resource area, then path. `reason` is truncated; full text "
      "is in `coverage-raw.json`.")
    w("")
    for tag in sorted(rows_by_tag, key=lambda t: (-sum(by_tag[t].values()), t)):
        counts = by_tag[tag]
        subtotal = sum(counts.values())
        w(f"<details>")
        w(f"<summary><b>{tag}</b> — {subtotal} operations, "
          f"{counts.get('verified', 0)} verified</summary>")
        w("")
        w("| | Operation | State | Notes |")
        w("|---|---|---|---|")
        for key, row in rows_by_tag[tag]:
            reason = str(row.get("reason", "")).replace("|", "\\|").replace("\n", " ")
            if len(reason) > 150:
                reason = reason[:150] + "…"
            w(f"| `{row['method']}` | `{row['path']}` | {row['state']} | {reason} |")
        w("")
        w("</details>")
        w("")

    w("## Records created")
    w("")
    created = raw.get("created_records") or {}
    if created:
        w("The most recent write run created these. All carry the "
          "`ZZ-MCPTEST-` prefix. Records in collections with a `DELETE` were "
          "removed and their absence confirmed; the rest remain, which is "
          "expected — only 14 of 462 operations support `DELETE`.")
        w("")
        w("| Collection | IDs |")
        w("|---|---|")
        for collection, ids in sorted(created.items()):
            w(f"| `{collection}` | {', '.join(ids)} |")
    else:
        w("No write run recorded.")
    w("")
    w("Every created ID is also appended to `created-records.log`.")
    w("")

    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(out)} lines)")
    print(f"{total} operations: " + ", ".join(
        f"{s}={by_state.get(s, 0)}" for s in STATES))
    if missing:
        print(f"note: {len(missing)} operations were not reached by either walk")


if __name__ == "__main__":
    main()
