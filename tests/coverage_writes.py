"""Exercise writes across every major Buildium entity family.

Curated, not exhaustive, and deliberately so. There are 224 write operations;
running all of them would mean inventing valid payloads for e-signature
requests, bank reconciliations and outbound resident email, and the Buildium
sandbox CANNOT BE RESET — no reset endpoint, no account deletion, a support
ticket is the only recovery. So this proves one representative round trip per
family and records, for every operation it does not attempt, why not.

Each scenario does as much of create -> read -> update -> delete as the API
supports. Only 14 of the 462 operations offer DELETE, so most families end at
update and leave a record behind; that is expected and the records are named so
they are obvious.

Every write goes through guards.check_write, the same function the MCP server
calls. Doing it this way means the fixture-prefix rule is enforced by
production code rather than by a convention this file happens to follow, and a
regression in the guards fails here too.

SAFETY
  - sandbox host is asserted before anything runs
  - every created record carries the ZZ-MCPTEST- prefix
  - no loops over collections, no retries on failure: a 422 is recorded and the
    scenario moves on
  - nothing that sends email or moves money is attempted; see SKIP_RULES
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from buildium_mcp.client import BuildiumClient, BuildiumError  # noqa: E402
from buildium_mcp.config import load_config  # noqa: E402
from buildium_mcp.guards import FixtureTracker, GuardViolation, check_write  # noqa: E402
from buildium_mcp.spec import load_index  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "coverage-raw.json"
DELAY_S = 0.15

PREFIX = "ZZ-MCPTEST-"
STAMP = time.strftime("%m%d%H%M%S")
TODAY = date.today()


def tag(what: str) -> str:
    """A name that is unmistakably test data and unique per run."""
    return f"{PREFIX}{what}-{STAMP}"


ADDRESS = {
    "AddressLine1": "1 Test Way",
    "City": "Boston",
    "State": "MA",
    "PostalCode": "02110",
    "Country": "UnitedStates",
}

# Why each family of writes is not attempted. Matched by path prefix, longest
# first. Every write operation not covered by a scenario gets one of these.
SKIP_RULES: list[tuple[str, str]] = [
    ("/v1/communications/emails",
     "sends real email to the addresses on seed tenant records. Outward-facing "
     "and unrecallable; no sandbox-safe variant exists."),
    ("/v1/communications/announcements",
     "publishes an announcement to resident portals and can trigger "
     "notifications. Outward-facing."),
    ("/v1/communications",
     "resident-facing messaging. Not exercised unattended."),
    ("/v1/bills/payments",
     "moves money and posts to the general ledger. No DELETE exists, and the "
     "resulting entries would distort GL balances the eval answer key reads."),
    ("/v1/bankaccounts/{bankAccountId}/reconciliations",
     "bank reconciliation is stateful and irreversible through the API; an "
     "abandoned half-finished reconciliation would block later ones."),
    ("/v1/bankaccounts/{bankAccountId}/deposits",
     "posts to the general ledger with no DELETE. Skipped to keep GL balances "
     "intact for the eval answer key."),
    ("/v1/bankaccounts/{bankAccountId}/quickdeposits",
     "posts to the general ledger with no DELETE."),
    ("/v1/bankaccounts/{bankAccountId}/withdrawals",
     "moves money with no DELETE."),
    ("/v1/bankaccounts/{bankAccountId}/transfers",
     "moves money between accounts with no DELETE."),
    ("/v1/bankaccounts/{bankAccountId}/checks",
     "issues a check. Financial and irreversible."),
    ("/v1/generalledger/journalentries",
     "posts directly to the general ledger with no DELETE."),
    ("/v1/leases/{leaseId}/charges",
     "posts a charge to a real seed lease's ledger. Reversible only by a "
     "credit, which compounds the problem."),
    ("/v1/leases/{leaseId}/payments",
     "records money received against a seed lease."),
    ("/v1/leases/{leaseId}/refunds",
     "issues a refund. Financial and irreversible."),
    ("/v1/leases/{leaseId}/creditsandcharges",
     "posts to a seed lease's ledger."),
    ("/v1/leases/{leaseId}/moveouts",
     "records a move-out against a seed lease, changing its occupancy state."),
    ("/v1/applicants",
     "applicant and application flows are multi-step and tied to e-signature "
     "and screening providers; setup cost far exceeds the coverage value."),
    ("/v1/applications",
     "application workflows depend on applicant and e-signature state."),
    ("/v1/associations/ownershipaccounts",
     "association ownership accounting mirrors lease ledgers; same financial "
     "reasoning."),
    ("/v1/budgets",
     "budgets span a fiscal year and have no DELETE; a stray test budget would "
     "appear in every financial report."),
    ("/v1/customfields",
     "a custom-field definition alters the shape of every record of its entity "
     "type portfolio-wide. Too broad a blast radius for an unattended run."),
    ("/v1/creditcardaccounts",
     "creates a financial account with no DELETE."),
    ("/v1/rentals/{propertyId}/images",
     "image endpoints share the signed-URL flow already proven by the file "
     "round trip; adding images would leave undeletable binary artefacts on "
     "seed properties."),
    ("/v1/rentals/units/{unitId}/images",
     "same signed-URL flow as files, already proven."),
    ("/v1/leases/{leaseId}/notes",
     "notes attach to seed records permanently; no DELETE exists."),
    ("/v1/leases/{leaseId}/renewals",
     "a renewal changes a seed lease's term and triggers e-signature."),
]

DEFAULT_SKIP = (
    "not exercised: no DELETE exists and the record would attach permanently to "
    "seed data. One representative family member was proven instead."
)


@dataclass
class WriteLog:
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def record(self, method: str, path: str, state: str, reason: str,
               **extra: Any) -> None:
        self.results[f"{method.upper()} {path}"] = {
            "method": method.upper(), "path": path, "state": state,
            "reason": reason, **extra,
        }

    def say(self, line: str) -> None:
        print(line)
        self.notes.append(line)


class Runner:
    """Performs one write, records the outcome, and never raises."""

    def __init__(self, client: BuildiumClient, tracker: FixtureTracker, log: WriteLog):
        self.client = client
        self.tracker = tracker
        self.log = log

    async def do(
        self,
        method: str,
        concrete: str,
        spec_path: str,
        body: Any = None,
        *,
        confirm: bool = False,
        expect: str = "2xx",
    ) -> tuple[bool, Any]:
        """Returns (ok, data). `expect="404"` inverts the test, for proving a
        delete actually removed something."""
        await asyncio.sleep(DELAY_S)

        # Same guard the MCP server applies. A refusal here is a bug in the
        # scenario, not in the API, and is recorded as such.
        try:
            check_write(method, concrete, body, self.tracker, confirm=confirm)
        except GuardViolation as exc:
            self.log.record(method, spec_path, "broken",
                            f"write guard refused the scenario's own call: {exc}")
            self.log.say(f"    GUARD REFUSED {method} {concrete}: {exc}")
            return False, None

        try:
            resp = await self.client.request(method, concrete, body=body,
                                             max_retries=1)
        except BuildiumError as exc:
            if expect == "404" and exc.status == 404:
                self.log.record(method, spec_path, "verified",
                                "record confirmed gone after DELETE (404)")
                self.log.say(f"    OK  {method} {concrete} -> 404 as expected")
                return True, None
            state = "needs-params" if exc.status in (400, 422) else "broken"
            if exc.status in (403, 409):
                state = "needs-setup"
            self.log.record(method, spec_path, state, str(exc)[:400],
                            status=exc.status)
            self.log.say(f"    {state.upper()}  {method} {concrete}: "
                         f"{str(exc)[:150]}")
            return False, None

        if expect == "404":
            self.log.record(method, spec_path, "broken",
                            f"expected 404 after DELETE, got {resp.status}")
            self.log.say(f"    FAIL {method} {concrete}: still present")
            return False, resp.data

        if method.upper() == "POST" and isinstance(resp.data, dict):
            self.tracker.record(concrete, resp.data.get("Id"), body)

        record_id = resp.data.get("Id") if isinstance(resp.data, dict) else None
        self.log.record(method, spec_path, "verified", f"HTTP {resp.status}",
                        status=resp.status, record_id=record_id)
        self.log.say(f"    OK  {method} {concrete} -> {resp.status}"
                     + (f" id={record_id}" if record_id else ""))
        return True, resp.data


# ---------------------------------------------------------------------------
# Scenarios. Each proves one family and feeds IDs to the ones after it.
# ---------------------------------------------------------------------------


async def scenario_property(run: Runner, ctx: dict) -> None:
    """Property -> unit -> lease -> tenant, the chain everything else hangs off.

    Built as a fresh chain rather than borrowing seed records so that leases and
    tenants can be written without touching real occupancy data.
    """
    ok, prop = await run.do("POST", "/v1/rentals", "/v1/rentals", {
        "Name": tag("property"),
        "RentalSubType": "SingleFamily",
        "OperatingBankAccountId": ctx["bank_account_id"],
        "Address": ADDRESS,
    })
    if not ok:
        return
    pid = prop["Id"]
    ctx["test_property_id"] = pid

    await run.do("GET", f"/v1/rentals/{pid}", "/v1/rentals/{propertyId}")
    await run.do("PUT", f"/v1/rentals/{pid}", "/v1/rentals/{propertyId}", {
        "Name": tag("property-renamed"),
        "RentalSubType": "SingleFamily",
        "OperatingBankAccountId": ctx["bank_account_id"],
        "Address": ADDRESS,
    })

    ok, unit = await run.do("POST", "/v1/rentals/units", "/v1/rentals/units", {
        "PropertyId": pid,
        "UnitNumber": f"{PREFIX}U1",
        "Address": ADDRESS,
        "UnitBedrooms": "TwoBed",
        "UnitBathrooms": "OneBath",
    })
    if not ok:
        return
    uid = unit["Id"]
    ctx["test_unit_id"] = uid
    await run.do("GET", f"/v1/rentals/units/{uid}", "/v1/rentals/units/{unitId}")
    await run.do("PUT", f"/v1/rentals/units/{uid}", "/v1/rentals/units/{unitId}", {
        "UnitNumber": f"{PREFIX}U1B",
        "Address": ADDRESS,
        "UnitBedrooms": "ThreeBed",
        "UnitBathrooms": "OneBath",
    })


async def scenario_owner(run: Runner, ctx: dict) -> None:
    pid = ctx.get("test_property_id")
    if pid is None:
        run.log.record("POST", "/v1/rentals/owners", "needs-setup",
                       "requires the test property, which was not created")
        return
    ok, owner = await run.do("POST", "/v1/rentals/owners", "/v1/rentals/owners", {
        "IsCompany": True,
        "CompanyName": tag("owner"),
        "PropertyIds": [pid],
        "Address": ADDRESS,
        "IsActive": True,
    })
    if not ok:
        return
    oid = owner["Id"]
    await run.do("GET", f"/v1/rentals/owners/{oid}", "/v1/rentals/owners/{rentalOwnerId}")
    await run.do("PUT", f"/v1/rentals/owners/{oid}", "/v1/rentals/owners/{rentalOwnerId}", {
        "IsCompany": True,
        "CompanyName": tag("owner-renamed"),
        "PropertyIds": [pid],
        "Address": ADDRESS,
        "IsActive": True,
    })


async def scenario_lease_and_tenant(run: Runner, ctx: dict) -> None:
    """A lease on the unit we made, then a tenant on that lease.

    SendWelcomeEmail is false: a true here would email a fabricated address
    from an unattended process.
    """
    uid = ctx.get("test_unit_id")
    if uid is None:
        for path in ("/v1/leases", "/v1/leases/tenants"):
            run.log.record("POST", path, "needs-setup",
                           "requires the test unit, which was not created")
        return

    ok, lease = await run.do("POST", "/v1/leases", "/v1/leases", {
        "UnitId": uid,
        "LeaseType": "AtWill",
        "LeaseFromDate": TODAY.isoformat(),
        "SendWelcomeEmail": False,
        "Tenants": [{
            "FirstName": tag("tenant")[:40],
            "LastName": "Fixture",
            "Email": None,
            "Address": ADDRESS,
        }],
        "Rent": {"Cycle": "Monthly", "Charges": [
            {"Amount": 1, "GlAccountId": ctx["rent_income_gl_id"],
             "NextDueDate": TODAY.isoformat()}
        ]},
    })
    if not ok:
        return
    lid = lease["Id"]
    ctx["test_lease_id"] = lid
    await run.do("GET", f"/v1/leases/{lid}", "/v1/leases/{leaseId}")
    # "LeaseToDate does not apply to leases of type AtWill" — so the update
    # switches the lease to Fixed, which is where an end date is legal.
    await run.do("PUT", f"/v1/leases/{lid}", "/v1/leases/{leaseId}", {
        "LeaseType": "Fixed",
        "UnitId": uid,
        "LeaseFromDate": TODAY.isoformat(),
        "LeaseToDate": (TODAY + timedelta(days=365)).isoformat(),
        "IsEvictionPending": False,
    })

    ok, tenant = await run.do("POST", "/v1/leases/tenants", "/v1/leases/tenants", {
        "FirstName": tag("cotenant")[:40],
        "LastName": "Fixture",
        "LeaseId": lid,
        "Address": ADDRESS,
    })
    if ok:
        tid = tenant["Id"]
        await run.do("GET", f"/v1/leases/tenants/{tid}",
                     "/v1/leases/tenants/{tenantId}")
        await run.do("PUT", f"/v1/leases/tenants/{tid}",
                     "/v1/leases/tenants/{tenantId}", {
                         "FirstName": tag("cotenant")[:40],
                         "LastName": "Renamed",
                         "Address": ADDRESS,
                     })


async def scenario_appliance(run: Runner, ctx: dict) -> None:
    """The only rental family with a DELETE — so the only full CRUD cycle."""
    pid = ctx.get("test_property_id") or ctx["seed_property_id"]
    ok, appliance = await run.do(
        "POST", "/v1/rentals/appliances", "/v1/rentals/appliances",
        {"Name": tag("appliance"), "PropertyId": pid, "Make": "Test",
         "Model": "Mk1", "Description": "coverage fixture"})
    if not ok:
        return
    aid = appliance["Id"]
    await run.do("GET", f"/v1/rentals/appliances/{aid}",
                 "/v1/rentals/appliances/{applianceId}")
    await run.do("PUT", f"/v1/rentals/appliances/{aid}",
                 "/v1/rentals/appliances/{applianceId}",
                 {"Name": tag("appliance-updated"), "Make": "Test",
                  "Model": "Mk2", "Description": "updated"})
    ok, _ = await run.do("POST", f"/v1/rentals/appliances/{aid}/servicehistory",
                         "/v1/rentals/appliances/{applianceId}/servicehistory",
                         {"Date": TODAY.isoformat(), "ServiceType": "Serviced",
                          "Details": f"{PREFIX}service"})
    await run.do("DELETE", f"/v1/rentals/appliances/{aid}",
                 "/v1/rentals/appliances/{applianceId}", confirm=True)
    await run.do("GET", f"/v1/rentals/appliances/{aid}",
                 "/v1/rentals/appliances/{applianceId}", expect="404")


async def scenario_association_appliance(run: Runner, ctx: dict) -> None:
    """Second full CRUD cycle, on the association side of the API."""
    unit = ctx.get("association_unit_id")
    association = ctx.get("association_id")
    if unit is None or association is None:
        run.log.record("POST", "/v1/associations/appliances", "needs-setup",
                       "no association unit exists in this sandbox")
        return
    ok, appliance = await run.do(
        "POST", "/v1/associations/appliances", "/v1/associations/appliances",
        {"Name": tag("assoc-appliance"), "AssociationId": association,
         "UnitId": unit, "Make": "Test", "Model": "Mk1"})
    if not ok:
        return
    aid = appliance["Id"]
    await run.do("GET", f"/v1/associations/appliances/{aid}",
                 "/v1/associations/appliances/{applianceId}")
    await run.do("PUT", f"/v1/associations/appliances/{aid}",
                 "/v1/associations/appliances/{applianceId}",
                 {"Name": tag("assoc-appliance-updated"), "Make": "Test",
                  "Model": "Mk2"})
    await run.do("DELETE", f"/v1/associations/appliances/{aid}",
                 "/v1/associations/appliances/{applianceId}", confirm=True)
    await run.do("GET", f"/v1/associations/appliances/{aid}",
                 "/v1/associations/appliances/{applianceId}", expect="404")


async def scenario_vendor(run: Runner, ctx: dict) -> None:
    ok, cat = await run.do("POST", "/v1/vendors/categories",
                           "/v1/vendors/categories", {"Name": tag("vendorcat")})
    cat_id = cat["Id"] if ok else ctx["vendor_category_id"]
    if ok:
        await run.do("GET", f"/v1/vendors/categories/{cat_id}",
                     "/v1/vendors/categories/{vendorCategoryId}")
        await run.do("PUT", f"/v1/vendors/categories/{cat_id}",
                     "/v1/vendors/categories/{vendorCategoryId}",
                     {"Name": tag("vendorcat-renamed")})

    ok, vendor = await run.do("POST", "/v1/vendors", "/v1/vendors", {
        "IsCompany": True, "CompanyName": tag("vendor"), "CategoryId": cat_id,
        "Address": ADDRESS, "IsActive": True,
    })
    if not ok:
        return
    vid = vendor["Id"]
    ctx["test_vendor_id"] = vid
    await run.do("GET", f"/v1/vendors/{vid}", "/v1/vendors/{vendorId}")
    await run.do("PUT", f"/v1/vendors/{vid}", "/v1/vendors/{vendorId}", {
        "IsCompany": True, "CompanyName": tag("vendor-renamed"),
        "CategoryId": cat_id, "Address": ADDRESS, "IsActive": True,
    })
    await run.do("POST", f"/v1/vendors/{vid}/notes", "/v1/vendors/{vendorId}/notes",
                 {"Note": f"{PREFIX}note from coverage run"})


async def scenario_work_order(run: Runner, ctx: dict) -> None:
    vid = ctx.get("test_vendor_id")
    pid = ctx.get("test_property_id") or ctx["seed_property_id"]
    if vid is None:
        run.log.record("POST", "/v1/workorders", "needs-setup",
                       "requires the test vendor, which was not created")
        return
    ok, wo = await run.do("POST", "/v1/workorders", "/v1/workorders", {
        "EntryAllowed": "No",
        "VendorId": vid,
        "Title": tag("workorder"),
        # WorkDetails is a description string, not an object — the nested
        # object the API wants is Task.
        "WorkDetails": "coverage fixture",
        "Task": {
            "Title": tag("workorder"),
            "Priority": "Low",
            "Status": "New",
            "AssignedToUserId": ctx["user_id"],
            "PropertyId": pid,
        },
    })
    if not ok:
        return
    wid = wo["Id"]
    await run.do("GET", f"/v1/workorders/{wid}", "/v1/workorders/{workOrderId}")
    await run.do("PUT", f"/v1/workorders/{wid}", "/v1/workorders/{workOrderId}", {
        "EntryAllowed": "Yes", "VendorId": vid,
        "Title": tag("workorder-updated"), "WorkDetails": "updated",
        "Task": {
            "Title": tag("workorder-updated"), "Priority": "Normal",
            "Status": "InProgress", "AssignedToUserId": ctx["user_id"],
            "PropertyId": pid,
        },
    })


async def scenario_task(run: Runner, ctx: dict) -> None:
    ok, cat = await run.do("POST", "/v1/tasks/categories", "/v1/tasks/categories",
                           {"Name": tag("taskcat")})
    if ok:
        cid = cat["Id"]
        await run.do("GET", f"/v1/tasks/categories/{cid}",
                     "/v1/tasks/categories/{taskCategoryId}")
        await run.do("PUT", f"/v1/tasks/categories/{cid}",
                     "/v1/tasks/categories/{taskCategoryId}",
                     {"Name": tag("taskcat-renamed")})

    ok, task = await run.do("POST", "/v1/tasks/todorequests",
                            "/v1/tasks/todorequests", {
                                "Title": tag("task"),
                                "Description": "coverage fixture",
                                "AssignedToUserId": ctx["user_id"],
                                "Priority": "Low",
                                "TaskStatus": "New",
                                "DueDate": (TODAY + timedelta(days=30)).isoformat(),
                            })
    if not ok:
        return
    tid = task["Id"]
    await run.do("GET", f"/v1/tasks/todorequests/{tid}",
                 "/v1/tasks/todorequests/{toDoTaskId}")
    await run.do("PUT", f"/v1/tasks/todorequests/{tid}",
                 "/v1/tasks/todorequests/{toDoTaskId}", {
                     "Title": tag("task-updated"),
                     "AssignedToUserId": ctx["user_id"],
                     "Priority": "High", "TaskStatus": "InProgress",
                 })
    # Task history has no POST: Buildium writes an entry itself when a task
    # changes. The PUT above should have produced one, so read it back and
    # update it — that is the only writable path into task history.
    ok, history = await run.do("GET", f"/v1/tasks/{tid}/history",
                               "/v1/tasks/{taskId}/history")
    if ok and history:
        hid = history[0]["Id"]
        run.tracker.record(f"/v1/tasks/{tid}/history", hid)
        await run.do("PUT", f"/v1/tasks/{tid}/history/{hid}",
                     "/v1/tasks/{taskId}/history/{taskHistoryId}",
                     {"Message": f"{PREFIX}history note"})
    ctx["test_task_id"] = tid


async def scenario_gl_account(run: Runner, ctx: dict) -> None:
    ok, gl = await run.do("POST", "/v1/glaccounts", "/v1/glaccounts", {
        "Name": tag("glaccount"),
        "AccountNumber": f"99{STAMP}"[:10],
        "SubType": "CurrentAsset",
        "Description": "coverage fixture",
        "IsContraAccount": False,
        # "IsCashAsset must have a value if the SubType is set to CurrentAsset"
        # — a conditional requirement the spec does not express.
        "IsCashAsset": False,
    })
    if not ok:
        return
    gid = gl["Id"]
    await run.do("GET", f"/v1/glaccounts/{gid}", "/v1/glaccounts/{glAccountId}")
    await run.do("PUT", f"/v1/glaccounts/{gid}", "/v1/glaccounts/{glAccountId}", {
        "Name": tag("glaccount-updated"), "SubType": "CurrentAsset",
        # AccountNumber is required on update even though the spec marks only
        # Name and SubType required — omitting it 422s.
        "AccountNumber": f"99{STAMP}"[:10],
        "Description": "updated", "IsContraAccount": False, "IsCashAsset": False,
    })


async def scenario_bill(run: Runner, ctx: dict) -> None:
    """Bills are the one financial family worth proving: they have a clean
    create/read/update shape and do not move money on their own."""
    vid = ctx.get("test_vendor_id")
    pid = ctx.get("test_property_id") or ctx["seed_property_id"]
    if vid is None:
        run.log.record("POST", "/v1/bills", "needs-setup",
                       "requires the test vendor, which was not created")
        return
    body = {
        "VendorId": vid,
        "Date": TODAY.isoformat(),
        "DueDate": (TODAY + timedelta(days=30)).isoformat(),
        "Memo": tag("bill"),
        "ReferenceNumber": STAMP,
        "Lines": [{
            "AccountingEntity": {"Id": pid, "AccountingEntityType": "Rental"},
            "GlAccountId": ctx["expense_gl_id"],
            "Amount": 1.00,
            "Memo": f"{PREFIX}line",
        }],
    }
    ok, bill = await run.do("POST", "/v1/bills", "/v1/bills", body)
    if not ok:
        return
    bid = bill["Id"]
    ctx["test_bill_id"] = bid
    await run.do("GET", f"/v1/bills/{bid}", "/v1/bills/{billId}")
    body["Memo"] = tag("bill-updated")
    await run.do("PUT", f"/v1/bills/{bid}", "/v1/bills/{billId}", body)


async def scenario_files(run: Runner, ctx: dict) -> None:
    """The two-step signed-URL flow, end to end and byte-for-byte."""
    ok, cat = await run.do("POST", "/v1/files/categories", "/v1/files/categories",
                           {"Name": tag("filecat")})
    cat_id = cat["Id"] if ok else ctx["file_category_id"]
    if ok:
        await run.do("GET", f"/v1/files/categories/{cat_id}",
                     "/v1/files/categories/{fileCategoryId}")
        await run.do("PUT", f"/v1/files/categories/{cat_id}",
                     "/v1/files/categories/{fileCategoryId}",
                     {"Name": tag("filecat-renamed")})

    pid = ctx.get("test_property_id") or ctx["seed_property_id"]
    payload = (f"{PREFIX}coverage round trip {STAMP}\n").encode() + bytes(range(256))
    name = f"{PREFIX}coverage-{STAMP}.txt"
    metadata = {
        "EntityType": "Rental", "EntityId": pid, "FileName": name,
        "Title": tag("file"), "CategoryId": cat_id,
        "Description": "coverage fixture",
    }
    await asyncio.sleep(DELAY_S)
    try:
        check_write("POST", "/v1/files/uploads", metadata, run.tracker)
        result = await run.client.upload_file("/v1/files/uploads", metadata,
                                              payload, name)
    except (BuildiumError, GuardViolation) as exc:
        run.log.record("POST", "/v1/files/uploads", "broken", str(exc)[:300])
        run.log.say(f"    FAIL upload: {str(exc)[:160]}")
        return
    run.log.record("POST", "/v1/files/uploads", "verified",
                   f"two-step upload completed; storage returned "
                   f"{result['storage_status']} for {result['bytes_sent']} bytes")
    run.log.say(f"    OK  POST /v1/files/uploads -> {result}")

    # Buildium creates the file record asynchronously after storage accepts it.
    file_id = None
    for _ in range(6):
        await asyncio.sleep(2)
        resp = await run.client.request("GET", "/v1/files", query={"limit": 100})
        matches = [f for f in resp.data if f.get("Title") == metadata["Title"]]
        if matches:
            file_id = matches[-1]["Id"]
            break
    if file_id is None:
        run.log.record("POST", "/v1/files/{fileId}/downloadrequest", "needs-setup",
                       "upload succeeded but the file record had not appeared "
                       "within 12s; Buildium finalizes uploads asynchronously")
        return

    # The upload created this record, but asynchronously and not via a POST
    # whose response the tracker saw. Register it so the ownership guard
    # recognises it — without this the PUT below is correctly refused.
    run.tracker.record("/v1/files", file_id, metadata)
    await run.do("GET", f"/v1/files/{file_id}", "/v1/files/{fileId}")
    await run.do("PUT", f"/v1/files/{file_id}", "/v1/files/{fileId}",
                 {"Title": tag("file-renamed"), "CategoryId": cat_id,
                  "Description": "updated"})

    await asyncio.sleep(DELAY_S)
    try:
        data, content_type = await run.client.download_file(
            f"/v1/files/{file_id}/downloadrequest")
    except BuildiumError as exc:
        run.log.record("POST", "/v1/files/{fileId}/downloadrequest", "broken",
                       str(exc)[:300])
        return
    identical = data == payload
    run.log.record(
        "POST", "/v1/files/{fileId}/downloadrequest",
        "verified" if identical else "broken",
        f"downloaded {len(data)} bytes ({content_type}); "
        f"byte-identical to what was uploaded: {identical}",
    )
    run.log.say(f"    OK  download round trip: {len(data)} bytes, "
                f"identical={identical}")


async def scenario_property_group(run: Runner, ctx: dict) -> None:
    pid = ctx.get("test_property_id") or ctx["seed_property_id"]
    ok, group = await run.do("POST", "/v1/propertygroups", "/v1/propertygroups", {
        "Name": tag("propgroup"), "PropertyIds": [pid],
    })
    if not ok:
        return
    gid = group["Id"]
    await run.do("GET", f"/v1/propertygroups/{gid}",
                 "/v1/propertygroups/{propertyGroupId}")
    await run.do("PUT", f"/v1/propertygroups/{gid}",
                 "/v1/propertygroups/{propertyGroupId}",
                 {"Name": tag("propgroup-renamed"), "PropertyIds": [pid]})


SCENARIOS: list[tuple[str, Callable]] = [
    ("properties + units", scenario_property),
    ("rental owners", scenario_owner),
    ("leases + tenants", scenario_lease_and_tenant),
    ("vendors + categories", scenario_vendor),
    ("work orders", scenario_work_order),
    ("tasks", scenario_task),
    ("GL accounts", scenario_gl_account),
    ("bills", scenario_bill),
    ("appliances (full CRUD)", scenario_appliance),
    ("association appliances (full CRUD)", scenario_association_appliance),
    ("files (two-step upload/download)", scenario_files),
    ("property groups", scenario_property_group),
]


async def build_context(client: BuildiumClient) -> dict[str, Any]:
    async def first(path: str, pick=lambda r: r[0]["Id"], **query):
        resp = await client.request("GET", path, query={"limit": 200, **query})
        rows = resp.data if isinstance(resp.data, list) else []
        return pick(rows) if rows else None

    gl = (await client.request("GET", "/v1/glaccounts", query={"limit": 200})).data
    expense = next((g["Id"] for g in gl if g.get("Type") == "Expense"), None)
    rent_income = next(
        (g["Id"] for g in gl if g.get("Name") == "Rent Income"),
        next((g["Id"] for g in gl if g.get("Type") == "Income"), None),
    )
    return {
        "seed_property_id": await first("/v1/rentals"),
        "bank_account_id": await first("/v1/bankaccounts"),
        "vendor_category_id": await first("/v1/vendors/categories"),
        "file_category_id": await first("/v1/files/categories"),
        "user_id": await first("/v1/users"),
        "association_unit_id": await first("/v1/associations/units"),
        "association_id": await first("/v1/associations"),
        "expense_gl_id": expense,
        "rent_income_gl_id": rent_income,
    }


def classify_untested(index, tested: set[str]) -> dict[str, dict[str, Any]]:
    """Every write operation no scenario touched, with the reason."""
    out: dict[str, dict[str, Any]] = {}
    rules = sorted(SKIP_RULES, key=lambda kv: -len(kv[0]))
    for ep in index.endpoints:
        if ep.method == "get" or ep.key in tested:
            continue
        reason = next((why for prefix, why in rules
                       if ep.path.startswith(prefix)), DEFAULT_SKIP)
        out[ep.key] = {
            "method": ep.method.upper(), "path": ep.path, "state": "write-skipped",
            "reason": reason, "tags": list(ep.tags), "summary": ep.summary,
        }
    return out


async def main() -> None:
    config = load_config()
    assert config.is_sandbox, f"refusing to write against {config.host}"
    assert config.writes_allowed, "deployment mode forbids writes"
    index = load_index(config.spec_path)
    client = BuildiumClient(config)
    tracker = FixtureTracker(config)
    log = WriteLog()

    print(f"Write coverage against {config.host}")
    print(f"Fixture prefix: {config.fixture_prefix}  run stamp: {STAMP}\n")

    ctx = await build_context(client)
    print("context: " + ", ".join(f"{k}={v}" for k, v in sorted(ctx.items())) + "\n")

    started = time.monotonic()
    for name, scenario in SCENARIOS:
        log.say(f"  -- {name}")
        try:
            await scenario(Runner(client, tracker, log), ctx)
        except Exception as exc:  # a scenario bug must not lose the whole run
            log.say(f"    SCENARIO ERROR: {type(exc).__name__}: {exc}")
    elapsed = round(time.monotonic() - started, 1)
    await client.aclose()

    results = dict(log.results)
    results.update(classify_untested(index, set(results)))

    counts: dict[str, int] = {}
    for row in results.values():
        counts[row["state"]] = counts.get(row["state"], 0) + 1

    payload = {
        "write_generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "write_elapsed_s": elapsed,
        "write_run_stamp": STAMP,
        "write_results": results,
        "created_records": tracker.summary(),
    }
    existing = json.loads(OUT.read_text()) if OUT.exists() else {}
    existing.update(payload)
    OUT.write_text(json.dumps(existing, indent=1, default=str))

    print(f"\n{'=' * 60}\n{len(results)} write operations classified in {elapsed}s")
    for state in ("verified", "needs-params", "needs-setup", "write-skipped", "broken"):
        if counts.get(state):
            print(f"  {state:14s} {counts[state]:4d}")
    print(f"\nrecords created this run: "
          f"{sum(len(v) for v in tracker.summary().values())}")
    print(f"raw -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
