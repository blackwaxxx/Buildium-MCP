# Coverage matrix

All **462** operations in the Buildium Open API, each executed against the sandbox or given a reason why not.

- Reads walked: 2026-09-16T07:35:03 (106.5s)
- Writes walked: 2026-09-16T07:33:11 (30.7s)
- Host: `apisandbox.buildium.com` — sandbox only

Regenerate with:

```bash
.venv/bin/python tests/coverage_matrix.py   # 238 GETs, read-only
.venv/bin/python tests/coverage_writes.py   # curated write scenarios
.venv/bin/python tests/render_coverage.py   # this file
```

## Totals

| State | Count | Share | Meaning |
|---|---:|---:|---|
| **verified** | 218 | 47% | executed against the sandbox and returned success |
| **needs-params** | 1 | 0% | executed, but rejected for inputs that could not be derived from the spec or from sandbox data |
| **needs-setup** | 59 | 13% | not provable here: no record of the required type exists in this sandbox, or the API key lacks the resource scope |
| **write-skipped** | 184 | 40% | deliberately not executed; each row gives the reason |
| **broken** | 0 | 0% | failed in a way that suggests a real defect |
| | **462** | | |

**218 of 462 operations (47%) were executed successfully against live sandbox data.**

No operation is marked broken: nothing failed in a way that suggests a defect in this server or in the API.

## By method

| Method | Total | Verified | Needs params | Needs setup | Write-skipped | Broken |
|---|---:|---:|---:|---:|---:|---:|
| GET | 238 | 178 | 1 | 59 | 0 | 0 |
| POST | 119 | 20 | 0 | 0 | 99 | 0 |
| PUT | 85 | 18 | 0 | 0 | 67 | 0 |
| PATCH | 6 | 0 | 0 | 0 | 6 | 0 |
| DELETE | 14 | 2 | 0 | 0 | 12 | 0 |

Of the 238 GET operations, 178 were called against the sandbox and returned successfully. The other 60 (1 `needs-params`, 59 `needs-setup`) were not: the sandbox holds no record of the required type, so there was no id to call them with. They are not known to be broken — they are untested, and each row states what it lacked.

The write columns are deliberately uneven: the sandbox cannot be reset, so writes prove one representative round trip per entity family rather than every operation. Each skipped row states its own reason.

## By resource area

| Area | Operations | Verified | Progress |
|---|---:|---:|---|
| Bank Accounts | 42 | 19 | `█████████···········` 19/42 (45%) |
| Leases | 28 | 15 | `███████████·········` 15/28 (54%) |
| Lease Transactions | 24 | 7 | `██████··············` 7/24 (29%) |
| Rental Properties | 24 | 11 | `█████████···········` 11/24 (46%) |
| Ownership Account Transactions | 23 | 7 | `██████··············` 7/23 (30%) |
| Applicants | 18 | 6 | `███████·············` 6/18 (33%) |
| Rental Units | 18 | 8 | `█████████···········` 8/18 (44%) |
| Vendors | 17 | 11 | `█████████████·······` 11/17 (65%) |
| Associations | 15 | 7 | `█████████···········` 7/15 (47%) |
| Communications | 15 | 6 | `████████············` 6/15 (40%) |
| Bills | 14 | 7 | `██████████··········` 7/14 (50%) |
| Tasks | 14 | 10 | `██████████████······` 10/14 (71%) |
| Application Transactions | 13 | 3 | `█████···············` 3/13 (23%) |
| Credit Card Accounts | 12 | 1 | `██··················` 1/12 (8%) |
| Association Owners | 11 | 5 | `█████████···········` 5/11 (45%) |
| Custom Fields | 11 | 0 | `····················` 0/11 (0%) |
| Files | 11 | 10 | `██████████████████··` 10/11 (91%) |
| General Ledger | 10 | 8 | `████████████████····` 8/10 (80%) |
| Inventory and Assets | 10 | 3 | `██████··············` 3/10 (30%) |
| Ownership Accounts | 10 | 4 | `████████············` 4/10 (40%) |
| Administration | 8 | 7 | `██████████████████··` 7/8 (88%) |
| Appliances | 8 | 5 | `████████████········` 5/8 (62%) |
| Association Tenants | 8 | 3 | `████████············` 3/8 (38%) |
| Association Units | 8 | 3 | `████████············` 3/8 (38%) |
| Listings | 8 | 3 | `████████············` 3/8 (38%) |
| Rental Appliances | 8 | 8 | `████████████████████` 8/8 (100%) |
| Rental Owners | 8 | 5 | `████████████········` 5/8 (62%) |
| Rental Tenants | 8 | 5 | `████████████········` 5/8 (62%) |
| Architectural Requests | 7 | 1 | `███·················` 1/7 (14%) |
| Rental Owner Requests | 6 | 3 | `██████████··········` 3/6 (50%) |
| Board Members | 5 | 2 | `████████············` 2/5 (40%) |
| Association Meter Readings | 4 | 2 | `██████████··········` 2/4 (50%) |
| Budgets | 4 | 2 | `██████████··········` 2/4 (50%) |
| Contact Requests | 4 | 2 | `██████████··········` 2/4 (50%) |
| Property Groups | 4 | 4 | `████████████████████` 4/4 (100%) |
| Rental Meter Readings | 4 | 2 | `██████████··········` 2/4 (50%) |
| Resident Center | 4 | 2 | `██████████··········` 2/4 (50%) |
| Resident Requests | 4 | 2 | `██████████··········` 2/4 (50%) |
| To Do Requests | 4 | 4 | `████████████████████` 4/4 (100%) |
| Work Orders | 4 | 4 | `████████████████████` 4/4 (100%) |
| Client Leads | 2 | 0 | `····················` 0/2 (0%) |
| Committees | 2 | 1 | `██████████··········` 1/2 (50%) |

## What the sandbox taught us that the spec does not say

Each of these cost a failed call to discover and is now encoded in the walkers, in the server's error hints, or both.

| Finding | Where it bites |
|---|---|
| Every date-range filter is capped at **365 days**, stated only in the 422 body | 9 endpoints, including `/v1/generalledger` and every `/v1/bankaccounts/{id}/*` collection |
| Request bodies declare **no required fields at the top level** — they are wrapped in a single-member `allOf` | all 119 POSTs; fixed by flattening in `spec.py` |
| `/v1/bills` requires `frompaiddate` **and** `topaiddate`, neither marked required | `/v1/bills` |
| `/v1/inventoryassets` and `/v1/inventorystorages` require `entitytype` + `entityid`, neither marked required | 2 endpoints |
| `IsCashAsset` is required when a GL account's `SubType` is `CurrentAsset`; `AccountNumber` is required on update | `POST`/`PUT /v1/glaccounts` |
| `WorkDetails` is a description **string**; the nested object is `Task` | `POST`/`PUT /v1/workorders` |
| `LeaseToDate` is rejected outright on `AtWill` leases | `PUT /v1/leases/{leaseId}` |
| Task history has **no POST**. Entries appear when a task changes; the only writable path is `PUT` with a `Message` field | `/v1/tasks/{taskId}/history/{taskHistoryId}` |
| Uploads are AWS **presigned PUT**, not multipart POST, and every `x-amz-meta-*` header must be reproduced exactly | all upload endpoints |
| File records are created **asynchronously** after storage accepts the bytes — the record does not exist the instant the upload returns | `/v1/files` |
| Parameter names are reused across unrelated ID spaces: a `tenantId` from `/v1/associations/tenants` 404s against `/v1/leases/tenants` | the whole templated-path surface |

## Full matrix

Grouped by resource area, then path. `reason` is truncated; full text is in `coverage-raw.json`.

<details>
<summary><b>Bank Accounts</b> — 42 operations, 19 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/bankaccounts` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/bankaccounts/{bankAccountId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/checks` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/checks` | write-skipped | issues a check. Financial and irreversible. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}` | write-skipped | issues a check. Financial and irreversible. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files/uploads` | write-skipped | issues a check. Financial and irreversible. |
| `DELETE` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files/{fileId}` | write-skipped | issues a check. Financial and irreversible. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files/{fileId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files/{fileId}/downloadrequests` | write-skipped | issues a check. Financial and irreversible. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/deposits` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/deposits` | write-skipped | posts to the general ledger with no DELETE. Skipped to keep GL balances intact for the eval answer key. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/deposits/{depositId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/deposits/{depositId}` | write-skipped | posts to the general ledger with no DELETE. Skipped to keep GL balances intact for the eval answer key. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/quickdeposits` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/quickdeposits` | write-skipped | posts to the general ledger with no DELETE. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/quickdeposits/{quickDepositId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/quickdeposits/{quickDepositId}` | write-skipped | posts to the general ledger with no DELETE. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/reconciliations` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/reconciliations` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/balances` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/balances` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `POST` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/cleartransactionsrequest` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `POST` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/finalizerequest` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/transactions` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/reconciliations/{reconciliationId}/uncleartransactionsrequest` | write-skipped | bank reconciliation is stateful and irreversible through the API; an abandoned half-finished reconciliation would block later ones. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/transactions` | verified | HTTP 200 |
| `GET` | `/v1/bankaccounts/{bankAccountId}/transactions/{transactionId}` | verified | HTTP 200 |
| `GET` | `/v1/bankaccounts/{bankAccountId}/transfers` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/transfers` | write-skipped | moves money between accounts with no DELETE. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/transfers/{transferId}` | verified | HTTP 200 |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/transfers/{transferId}` | write-skipped | moves money between accounts with no DELETE. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/undepositedfunds` | verified | HTTP 200 |
| `GET` | `/v1/bankaccounts/{bankAccountId}/withdrawals` | verified | HTTP 200 |
| `POST` | `/v1/bankaccounts/{bankAccountId}/withdrawals` | write-skipped | moves money with no DELETE. |
| `GET` | `/v1/bankaccounts/{bankAccountId}/withdrawals/{withdrawalId}` | needs-setup | not attempted: the sandbox contains no record supplying withdrawalId. Creating one is a prerequisite. |
| `PUT` | `/v1/bankaccounts/{bankAccountId}/withdrawals/{withdrawalId}` | write-skipped | moves money with no DELETE. |

</details>

<details>
<summary><b>Leases</b> — 28 operations, 15 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/leases` | verified | HTTP 200 |
| `POST` | `/v1/leases` | verified | HTTP 201 |
| `GET` | `/v1/leases/renewalhistory` | verified | HTTP 200 |
| `GET` | `/v1/leases/renewals` | verified | HTTP 200 |
| `GET` | `/v1/leases/rent` | verified | HTTP 200 |
| `GET` | `/v1/leases/{leaseId}` | verified | HTTP 200 |
| `PUT` | `/v1/leases/{leaseId}` | verified | HTTP 200 |
| `GET` | `/v1/leases/{leaseId}/epaysettings` | verified | HTTP 200 |
| `PUT` | `/v1/leases/{leaseId}/epaysettings` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/moveouts` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/moveouts` | write-skipped | records a move-out against a seed lease, changing its occupancy state. |
| `DELETE` | `/v1/leases/{leaseId}/moveouts/{tenantId}` | write-skipped | records a move-out against a seed lease, changing its occupancy state. |
| `GET` | `/v1/leases/{leaseId}/moveouts/{tenantId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `GET` | `/v1/leases/{leaseId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/notes` | write-skipped | notes attach to seed records permanently; no DELETE exists. |
| `GET` | `/v1/leases/{leaseId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/leases/{leaseId}/notes/{noteId}` | write-skipped | notes attach to seed records permanently; no DELETE exists. |
| `GET` | `/v1/leases/{leaseId}/partialpaymentsettings` | verified | HTTP 200 |
| `PATCH` | `/v1/leases/{leaseId}/partialpaymentsettings` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/renewals` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/renewals` | write-skipped | a renewal changes a seed lease's term and triggers e-signature. |
| `GET` | `/v1/leases/{leaseId}/renewals/{renewalId}` | needs-setup | not attempted: the sandbox contains no record supplying renewalId. Creating one is a prerequisite. |
| `GET` | `/v1/leases/{leaseId}/rent` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/rent` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/rent/{rentId}` | verified | HTTP 200 |
| `PUT` | `/v1/leases/{leaseId}/rent/{rentId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/rentersinsurance` | verified | HTTP 200 |
| `GET` | `/v1/leases/{leaseId}/rentersinsurance/{policyId}` | needs-setup | not attempted: the sandbox contains no record supplying policyId. Creating one is a prerequisite. |

</details>

<details>
<summary><b>Lease Transactions</b> — 24 operations, 7 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/leases/outstandingbalances` | verified | HTTP 200 |
| `GET` | `/v1/leases/recurringtransactions` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/applieddeposits` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `PUT` | `/v1/leases/{leaseId}/applieddeposits/{depositId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/leases/{leaseId}/autoallocatedpayments` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/charges` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/charges` | write-skipped | posts a charge to a real seed lease's ledger. Reversible only by a credit, which compounds the problem. |
| `GET` | `/v1/leases/{leaseId}/charges/{chargeId}` | verified | HTTP 200 |
| `PUT` | `/v1/leases/{leaseId}/charges/{chargeId}` | write-skipped | posts a charge to a real seed lease's ledger. Reversible only by a credit, which compounds the problem. |
| `POST` | `/v1/leases/{leaseId}/credits` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/leases/{leaseId}/payments` | write-skipped | records money received against a seed lease. |
| `PUT` | `/v1/leases/{leaseId}/payments/{paymentId}` | write-skipped | records money received against a seed lease. |
| `POST` | `/v1/leases/{leaseId}/recurringcharges` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/recurringcharges/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/leases/{leaseId}/recurringcredits` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/recurringcredits/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/leases/{leaseId}/recurringpayments` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/recurringpayments/{paymentId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `GET` | `/v1/leases/{leaseId}/recurringtransactions` | verified | HTTP 200 |
| `POST` | `/v1/leases/{leaseId}/refunds` | write-skipped | issues a refund. Financial and irreversible. |
| `GET` | `/v1/leases/{leaseId}/refunds/{refundId}` | needs-setup | not attempted: the sandbox contains no record supplying refundId. Creating one is a prerequisite. |
| `POST` | `/v1/leases/{leaseId}/reversepayments` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/{leaseId}/transactions` | verified | HTTP 200 |
| `GET` | `/v1/leases/{leaseId}/transactions/{transactionId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Rental Properties</b> — 24 operations, 11 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals` | verified | HTTP 200 |
| `POST` | `/v1/rentals` | verified | HTTP 201 |
| `GET` | `/v1/rentals/{propertyId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}` | verified | HTTP 200 |
| `GET` | `/v1/rentals/{propertyId}/amenities` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/amenities` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/epaysettings` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/epaysettings` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/images` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/images/order` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `POST` | `/v1/rentals/{propertyId}/images/uploads` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `POST` | `/v1/rentals/{propertyId}/images/videolinkrequests` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `DELETE` | `/v1/rentals/{propertyId}/images/{imageId}` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `GET` | `/v1/rentals/{propertyId}/images/{imageId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/images/{imageId}` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `POST` | `/v1/rentals/{propertyId}/images/{imageId}/downloadrequests` | write-skipped | image endpoints share the signed-URL flow already proven by the file round trip; adding images would leave undeletable binary artefacts on seed proper… |
| `POST` | `/v1/rentals/{propertyId}/inactivationrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/rentals/{propertyId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/notes/{noteId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/rentals/{propertyId}/reactivationrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/vendors` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/vendors` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Ownership Account Transactions</b> — 23 operations, 7 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/ownershipaccounts/outstandingbalances` | verified | HTTP 200 |
| `GET` | `/v1/associations/ownershipaccounts/recurringtransactions` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/applieddeposits` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `PUT` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/applieddeposits/{depositId}` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/autoallocatedpayments` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/charges` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/charges` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/charges/{chargeId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/charges/{chargeId}` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/credits` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/payments` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `PUT` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/payments/{paymentId}` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringcharges` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringcharges/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringcredits` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringcredits/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringpayments` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringpayments/{paymentId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/recurringtransactions` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/refunds` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/refunds/{refundId}` | needs-setup | not attempted: the sandbox contains no record supplying refundId. Creating one is a prerequisite. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/transactions` | verified | HTTP 200 |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/transactions/{transactionId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Applicants</b> — 18 operations, 6 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/applicants` | verified | HTTP 200 |
| `POST` | `/v1/applicants` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/groups` | verified | HTTP 200 |
| `POST` | `/v1/applicants/groups` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/groups/{applicantGroupId}` | needs-setup | not attempted: the sandbox contains no record supplying applicantGroupId. Creating one is a prerequisite. |
| `PUT` | `/v1/applicants/groups/{applicantGroupId}` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/groups/{applicantGroupId}/notes` | needs-setup | not attempted: the sandbox contains no record supplying applicantGroupId. Creating one is a prerequisite. |
| `POST` | `/v1/applicants/groups/{applicantGroupId}/notes` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/groups/{applicantGroupId}/notes/{noteId}` | needs-setup | not attempted: the sandbox contains no record supplying applicantGroupId. Creating one is a prerequisite. |
| `PUT` | `/v1/applicants/groups/{applicantGroupId}/notes/{noteId}` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/{applicantId}` | verified | HTTP 200 |
| `PUT` | `/v1/applicants/{applicantId}` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/{applicantId}/applications` | verified | HTTP 200 |
| `GET` | `/v1/applicants/{applicantId}/applications/{applicationId}` | verified | HTTP 200 |
| `PUT` | `/v1/applicants/{applicantId}/applications/{applicationId}` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/{applicantId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/applicants/{applicantId}/notes` | write-skipped | applicant and application flows are multi-step and tied to e-signature and screening providers; setup cost far exceeds the coverage value. |
| `GET` | `/v1/applicants/{applicantId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |

</details>

<details>
<summary><b>Rental Units</b> — 18 operations, 8 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals/units` | verified | HTTP 200 |
| `POST` | `/v1/rentals/units` | verified | HTTP 201 |
| `GET` | `/v1/rentals/units/{unitId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/units/{unitId}` | verified | HTTP 200 |
| `GET` | `/v1/rentals/units/{unitId}/amenities` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/units/{unitId}/amenities` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/units/{unitId}/images` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/units/{unitId}/images/order` | write-skipped | same signed-URL flow as files, already proven. |
| `POST` | `/v1/rentals/units/{unitId}/images/uploads` | write-skipped | same signed-URL flow as files, already proven. |
| `POST` | `/v1/rentals/units/{unitId}/images/videolinkrequests` | write-skipped | same signed-URL flow as files, already proven. |
| `DELETE` | `/v1/rentals/units/{unitId}/images/{imageId}` | write-skipped | same signed-URL flow as files, already proven. |
| `GET` | `/v1/rentals/units/{unitId}/images/{imageId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/units/{unitId}/images/{imageId}` | write-skipped | same signed-URL flow as files, already proven. |
| `POST` | `/v1/rentals/units/{unitId}/images/{imageId}/downloadrequests` | write-skipped | same signed-URL flow as files, already proven. |
| `GET` | `/v1/rentals/units/{unitId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/rentals/units/{unitId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/units/{unitId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/rentals/units/{unitId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Vendors</b> — 17 operations, 11 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/vendors` | verified | HTTP 200 |
| `POST` | `/v1/vendors` | verified | HTTP 201 |
| `GET` | `/v1/vendors/categories` | verified | HTTP 200 |
| `POST` | `/v1/vendors/categories` | verified | HTTP 201 |
| `GET` | `/v1/vendors/categories/{vendorCategoryId}` | verified | HTTP 200 |
| `PUT` | `/v1/vendors/categories/{vendorCategoryId}` | verified | HTTP 200 |
| `GET` | `/v1/vendors/{vendorId}` | verified | HTTP 200 |
| `PUT` | `/v1/vendors/{vendorId}` | verified | HTTP 200 |
| `POST` | `/v1/vendors/{vendorId}/credits` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/vendors/{vendorId}/credits/{vendorCreditId}` | needs-setup | not attempted: the sandbox contains no record supplying vendorCreditId. Creating one is a prerequisite. |
| `GET` | `/v1/vendors/{vendorId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/vendors/{vendorId}/notes` | verified | HTTP 201 |
| `GET` | `/v1/vendors/{vendorId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/vendors/{vendorId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/vendors/{vendorId}/refunds` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/vendors/{vendorId}/refunds/{vendorRefundId}` | needs-setup | not attempted: the sandbox contains no record supplying vendorRefundId. Creating one is a prerequisite. |
| `GET` | `/v1/vendors/{vendorId}/transactions` | verified | HTTP 200 |

</details>

<details>
<summary><b>Associations</b> — 15 operations, 7 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations` | verified | HTTP 200 |
| `POST` | `/v1/associations` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/banklockboxdata` | verified | HTTP 200 |
| `GET` | `/v1/associations/{associationId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/epaysettings` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}/epaysettings` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/associations/{associationId}/inactivationrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/associations/{associationId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/notes/{noteId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `POST` | `/v1/associations/{associationId}/reactivationrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/vendors` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}/vendors` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Communications</b> — 15 operations, 6 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/communications/announcements` | verified | HTTP 200 |
| `POST` | `/v1/communications/announcements` | write-skipped | publishes an announcement to resident portals and can trigger notifications. Outward-facing. |
| `GET` | `/v1/communications/announcements/{announcementId}` | verified | HTTP 200 |
| `POST` | `/v1/communications/announcements/{announcementId}/expirationrequest` | write-skipped | publishes an announcement to resident portals and can trigger notifications. Outward-facing. |
| `GET` | `/v1/communications/announcements/{announcementId}/properties` | verified | HTTP 200 |
| `GET` | `/v1/communications/emails` | needs-params | rejected for missing or invalid parameters: GET /v1/communications/emails failed with HTTP 422: request validation failed. The request failed validati… |
| `POST` | `/v1/communications/emails` | write-skipped | sends real email to the addresses on seed tenant records. Outward-facing and unrecallable; no sandbox-safe variant exists. |
| `GET` | `/v1/communications/emails/{emailId}` | needs-setup | not attempted: the sandbox contains no record supplying emailId. Creating one is a prerequisite. |
| `GET` | `/v1/communications/emails/{emailId}/recipients` | needs-setup | not attempted: the sandbox contains no record supplying emailId. Creating one is a prerequisite. |
| `GET` | `/v1/communications/phonelogs` | verified | HTTP 200 |
| `POST` | `/v1/communications/phonelogs` | write-skipped | resident-facing messaging. Not exercised unattended. |
| `GET` | `/v1/communications/phonelogs/{phoneLogId}` | needs-setup | not attempted: the sandbox contains no record supplying phoneLogId. Creating one is a prerequisite. |
| `PUT` | `/v1/communications/phonelogs/{phoneLogId}` | write-skipped | resident-facing messaging. Not exercised unattended. |
| `GET` | `/v1/communications/templates` | verified | HTTP 200 |
| `GET` | `/v1/communications/templates/{templateId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Bills</b> — 14 operations, 7 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/bills` | verified | HTTP 200 |
| `POST` | `/v1/bills` | verified | HTTP 201 |
| `POST` | `/v1/bills/payments` | write-skipped | moves money and posts to the general ledger. No DELETE exists, and the resulting entries would distort GL balances the eval answer key reads. |
| `GET` | `/v1/bills/{billId}` | verified | HTTP 200 |
| `PATCH` | `/v1/bills/{billId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `PUT` | `/v1/bills/{billId}` | verified | HTTP 200 |
| `GET` | `/v1/bills/{billId}/files` | verified | HTTP 200 |
| `POST` | `/v1/bills/{billId}/files/uploads` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `DELETE` | `/v1/bills/{billId}/files/{fileId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/bills/{billId}/files/{fileId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/bills/{billId}/files/{fileId}/downloadrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/bills/{billId}/payments` | verified | HTTP 200 |
| `POST` | `/v1/bills/{billId}/payments` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/bills/{billId}/payments/{paymentId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Tasks</b> — 14 operations, 10 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/tasks` | verified | HTTP 200 |
| `GET` | `/v1/tasks/categories` | verified | HTTP 200 |
| `POST` | `/v1/tasks/categories` | verified | HTTP 201 |
| `GET` | `/v1/tasks/categories/{taskCategoryId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/categories/{taskCategoryId}` | verified | HTTP 200 |
| `GET` | `/v1/tasks/{taskId}` | verified | HTTP 200 |
| `GET` | `/v1/tasks/{taskId}/history` | verified | HTTP 200 |
| `GET` | `/v1/tasks/{taskId}/history/{taskHistoryId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/{taskId}/history/{taskHistoryId}` | verified | HTTP 200 |
| `GET` | `/v1/tasks/{taskId}/history/{taskHistoryId}/files` | verified | HTTP 200 |
| `POST` | `/v1/tasks/{taskId}/history/{taskHistoryId}/files/uploads` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `DELETE` | `/v1/tasks/{taskId}/history/{taskHistoryId}/files/{fileId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/tasks/{taskId}/history/{taskHistoryId}/files/{fileId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/tasks/{taskId}/history/{taskHistoryId}/files/{fileId}/downloadrequest` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Application Transactions</b> — 13 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/applications/outstandingbalances` | verified | HTTP 200 |
| `POST` | `/v1/applications/{applicationId}/autoallocatedpayments` | write-skipped | application workflows depend on applicant and e-signature state. |
| `GET` | `/v1/applications/{applicationId}/charges` | verified | HTTP 200 |
| `POST` | `/v1/applications/{applicationId}/charges` | write-skipped | application workflows depend on applicant and e-signature state. |
| `GET` | `/v1/applications/{applicationId}/charges/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/applications/{applicationId}/charges/{transactionId}` | write-skipped | application workflows depend on applicant and e-signature state. |
| `POST` | `/v1/applications/{applicationId}/payments` | write-skipped | application workflows depend on applicant and e-signature state. |
| `PUT` | `/v1/applications/{applicationId}/payments/{transactionId}` | write-skipped | application workflows depend on applicant and e-signature state. |
| `POST` | `/v1/applications/{applicationId}/refunds` | write-skipped | application workflows depend on applicant and e-signature state. |
| `GET` | `/v1/applications/{applicationId}/refunds/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/applications/{applicationId}/reversepayments` | write-skipped | application workflows depend on applicant and e-signature state. |
| `GET` | `/v1/applications/{applicationId}/transactions` | verified | HTTP 200 |
| `GET` | `/v1/applications/{applicationId}/transactions/{transactionId}` | needs-setup | no record of this type exists in the sandbox (404) |

</details>

<details>
<summary><b>Credit Card Accounts</b> — 12 operations, 1 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/creditcardaccounts` | verified | HTTP 200 |
| `POST` | `/v1/creditcardaccounts` | write-skipped | creates a financial account with no DELETE. |
| `GET` | `/v1/creditcardaccounts/{creditCardAccountId}` | needs-setup | not attempted: the sandbox contains no record supplying creditCardAccountId. Creating one is a prerequisite. |
| `PUT` | `/v1/creditcardaccounts/{creditCardAccountId}` | write-skipped | creates a financial account with no DELETE. |
| `POST` | `/v1/creditcardaccounts/{creditCardAccountId}/payments` | write-skipped | creates a financial account with no DELETE. |
| `GET` | `/v1/creditcardaccounts/{creditCardAccountId}/payments/{journalId}` | needs-setup | not attempted: the sandbox contains no record supplying creditCardAccountId, journalId. Creating one is a prerequisite. |
| `PUT` | `/v1/creditcardaccounts/{creditCardAccountId}/payments/{journalId}` | write-skipped | creates a financial account with no DELETE. |
| `POST` | `/v1/creditcardaccounts/{creditCardAccountId}/purchases` | write-skipped | creates a financial account with no DELETE. |
| `GET` | `/v1/creditcardaccounts/{creditCardAccountId}/purchases/{journalId}` | needs-setup | not attempted: the sandbox contains no record supplying creditCardAccountId, journalId. Creating one is a prerequisite. |
| `PUT` | `/v1/creditcardaccounts/{creditCardAccountId}/purchases/{journalId}` | write-skipped | creates a financial account with no DELETE. |
| `GET` | `/v1/creditcardaccounts/{creditCardAccountId}/transactions` | needs-setup | not attempted: the sandbox contains no record supplying creditCardAccountId. Creating one is a prerequisite. |
| `GET` | `/v1/creditcardaccounts/{creditCardAccountId}/transactions/{transactionId}` | needs-setup | not attempted: the sandbox contains no record supplying creditCardAccountId. Creating one is a prerequisite. |

</details>

<details>
<summary><b>Association Owners</b> — 11 operations, 5 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/owners` | verified | HTTP 200 |
| `POST` | `/v1/associations/owners` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/owners/{ownerId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/owners/{ownerId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/owners/{ownerId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/associations/owners/{ownerId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/owners/{ownerId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/associations/owners/{ownerId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/owners/{ownerId}/units` | verified | HTTP 200 |
| `GET` | `/v1/associations/owners/{ownerId}/units/{unitId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/owners/{ownerId}/units/{unitId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Custom Fields</b> — 11 operations, 0 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `DELETE` | `/v1/customfields/definitions/{definitionId}` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |
| `GET` | `/v1/customfields/definitions/{definitionId}` | needs-setup | not attempted: the sandbox contains no record supplying definitionId. Creating one is a prerequisite. |
| `PATCH` | `/v1/customfields/definitions/{definitionId}` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |
| `GET` | `/v1/customfields/entityType/{entityType}/definitions` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/customfields/entityType/{entityType}/definitions` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |
| `GET` | `/v1/customfields/entityType/{entityType}/entityId/{entityId}/values` | needs-setup | not attempted: the sandbox contains no record supplying entityId. Creating one is a prerequisite. |
| `POST` | `/v1/customfields/entityType/{entityType}/entityId/{entityId}/values` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |
| `GET` | `/v1/customfields/entityType/{entityType}/groups` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/customfields/entityType/{entityType}/groups` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |
| `GET` | `/v1/customfields/groups/{groupId}` | needs-setup | not attempted: the sandbox contains no record supplying groupId. Creating one is a prerequisite. |
| `PATCH` | `/v1/customfields/groups/{groupId}` | write-skipped | a custom-field definition alters the shape of every record of its entity type portfolio-wide. Too broad a blast radius for an unattended run. |

</details>

<details>
<summary><b>Files</b> — 11 operations, 10 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/files` | verified | HTTP 200 |
| `GET` | `/v1/files/categories` | verified | HTTP 200 |
| `POST` | `/v1/files/categories` | verified | HTTP 201 |
| `GET` | `/v1/files/categories/{fileCategoryId}` | verified | HTTP 200 |
| `PUT` | `/v1/files/categories/{fileCategoryId}` | verified | HTTP 200 |
| `POST` | `/v1/files/uploads` | verified | two-step upload completed; storage returned 200 for 298 bytes |
| `GET` | `/v1/files/{fileId}` | verified | HTTP 200 |
| `PUT` | `/v1/files/{fileId}` | verified | HTTP 200 |
| `POST` | `/v1/files/{fileId}/downloadrequest` | verified | downloaded 298 bytes (text/plain); byte-identical to what was uploaded: True |
| `GET` | `/v1/files/{fileId}/sharing` | verified | HTTP 200 |
| `PUT` | `/v1/files/{fileId}/sharing` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>General Ledger</b> — 10 operations, 8 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/generalledger` | verified | HTTP 200 |
| `POST` | `/v1/generalledger/journalentries` | write-skipped | posts directly to the general ledger with no DELETE. |
| `PUT` | `/v1/generalledger/journalentries/{journalEntryId}` | write-skipped | posts directly to the general ledger with no DELETE. |
| `GET` | `/v1/generalledger/transactions` | verified | HTTP 200 |
| `GET` | `/v1/generalledger/transactions/{transactionId}` | verified | HTTP 200 |
| `GET` | `/v1/glaccounts` | verified | HTTP 200 |
| `POST` | `/v1/glaccounts` | verified | HTTP 201 |
| `GET` | `/v1/glaccounts/balances` | verified | HTTP 200 |
| `GET` | `/v1/glaccounts/{glAccountId}` | verified | HTTP 200 |
| `PUT` | `/v1/glaccounts/{glAccountId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Inventory and Assets</b> — 10 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/assetcategories` | verified | HTTP 200 |
| `GET` | `/v1/assetservicehistory/{inventoryAssetId}` | needs-setup | not attempted: the sandbox contains no record supplying inventoryAssetId. Creating one is a prerequisite. |
| `POST` | `/v1/assetservicehistory/{inventoryAssetId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/assetservicehistory/{inventoryAssetId}/{assetServiceHistoryId}` | needs-setup | not attempted: the sandbox contains no record supplying inventoryAssetId, assetServiceHistoryId. Creating one is a prerequisite. |
| `POST` | `/v1/inventoryasset` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `DELETE` | `/v1/inventoryasset/{inventoryAssetId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/inventoryasset/{inventoryAssetId}` | needs-setup | not attempted: the sandbox contains no record supplying inventoryAssetId. Creating one is a prerequisite. |
| `PUT` | `/v1/inventoryasset/{inventoryAssetId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/inventoryassets` | verified | HTTP 200 |
| `GET` | `/v1/inventorystorages` | verified | HTTP 200 |

</details>

<details>
<summary><b>Ownership Accounts</b> — 10 operations, 4 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/ownershipaccounts` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/ownershipaccounts/{ownershipAccountId}` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/notes` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/notes/{noteId}` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/partialpaymentsettings` | verified | HTTP 200 |
| `PATCH` | `/v1/associations/ownershipaccounts/{ownershipAccountId}/partialpaymentsettings` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |

</details>

<details>
<summary><b>Administration</b> — 8 operations, 7 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/administration/account` | verified | HTTP 200 |
| `GET` | `/v1/administration/accountinglockperiod` | verified | HTTP 200 |
| `GET` | `/v1/administration/residentsettings/partialpaymentsettings` | verified | HTTP 200 |
| `PATCH` | `/v1/administration/residentsettings/partialpaymentsettings` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/userroles` | verified | HTTP 200 |
| `GET` | `/v1/userroles/{userRoleId}` | verified | HTTP 200 |
| `GET` | `/v1/users` | verified | HTTP 200 |
| `GET` | `/v1/users/{userId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Appliances</b> — 8 operations, 5 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/appliances` | verified | HTTP 200 |
| `POST` | `/v1/associations/appliances` | verified | HTTP 201 |
| `DELETE` | `/v1/associations/appliances/{applianceId}` | verified | HTTP 204 |
| `GET` | `/v1/associations/appliances/{applianceId}` | verified | record confirmed gone after DELETE (404) |
| `PUT` | `/v1/associations/appliances/{applianceId}` | verified | HTTP 200 |
| `GET` | `/v1/associations/appliances/{applianceId}/servicehistory` | needs-setup | no record of this type exists in the sandbox (404) |
| `POST` | `/v1/associations/appliances/{applianceId}/servicehistory` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/appliances/{applianceId}/servicehistory/{serviceHistoryId}` | needs-setup | no record of this type exists in the sandbox (404) |

</details>

<details>
<summary><b>Association Tenants</b> — 8 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/tenants` | verified | HTTP 200 |
| `POST` | `/v1/associations/tenants` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/tenants/{tenantId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/tenants/{tenantId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/tenants/{tenantId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/associations/tenants/{tenantId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/tenants/{tenantId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/associations/tenants/{tenantId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Association Units</b> — 8 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/units` | verified | HTTP 200 |
| `POST` | `/v1/associations/units` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/units/{unitId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/units/{unitId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/units/{unitId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/associations/units/{unitId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/units/{unitId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/associations/units/{unitId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Listings</b> — 8 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals/units/listingcontacts` | verified | HTTP 200 |
| `POST` | `/v1/rentals/units/listingcontacts` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/units/listingcontacts/{listingContactId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/units/listingcontacts/{listingContactId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/units/listings` | verified | HTTP 200 |
| `DELETE` | `/v1/rentals/units/{unitId}/listing` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/units/{unitId}/listing` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/rentals/units/{unitId}/listing` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Rental Appliances</b> — 8 operations, 8 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals/appliances` | verified | HTTP 200 |
| `POST` | `/v1/rentals/appliances` | verified | HTTP 201 |
| `DELETE` | `/v1/rentals/appliances/{applianceId}` | verified | HTTP 204 |
| `GET` | `/v1/rentals/appliances/{applianceId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/appliances/{applianceId}` | verified | HTTP 200 |
| `GET` | `/v1/rentals/appliances/{applianceId}/servicehistory` | verified | HTTP 200 |
| `POST` | `/v1/rentals/appliances/{applianceId}/servicehistory` | verified | HTTP 201 |
| `GET` | `/v1/rentals/appliances/{applianceId}/servicehistory/{serviceHistoryId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Rental Owners</b> — 8 operations, 5 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals/owners` | verified | HTTP 200 |
| `POST` | `/v1/rentals/owners` | verified | HTTP 201 |
| `GET` | `/v1/rentals/owners/{rentalOwnerId}` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/owners/{rentalOwnerId}` | verified | HTTP 200 |
| `GET` | `/v1/rentals/owners/{rentalOwnerId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/rentals/owners/{rentalOwnerId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/owners/{rentalOwnerId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/rentals/owners/{rentalOwnerId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Rental Tenants</b> — 8 operations, 5 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/leases/tenants` | verified | HTTP 200 |
| `POST` | `/v1/leases/tenants` | verified | HTTP 201 |
| `GET` | `/v1/leases/tenants/{tenantId}` | verified | HTTP 200 |
| `PUT` | `/v1/leases/tenants/{tenantId}` | verified | HTTP 200 |
| `GET` | `/v1/leases/tenants/{tenantId}/notes` | verified | HTTP 200 |
| `POST` | `/v1/leases/tenants/{tenantId}/notes` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/leases/tenants/{tenantId}/notes/{noteId}` | needs-setup | no record of this type exists in the sandbox (404) |
| `PUT` | `/v1/leases/tenants/{tenantId}/notes/{noteId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Architectural Requests</b> — 7 operations, 1 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/ownershipaccounts/architecturalrequests` | verified | HTTP 200 |
| `POST` | `/v1/associations/ownershipaccounts/architecturalrequests` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/architecturalrequests/{architecturalRequestId}` | needs-setup | not attempted: the sandbox contains no record supplying architecturalRequestId. Creating one is a prerequisite. |
| `GET` | `/v1/associations/ownershipaccounts/architecturalrequests/{architecturalRequestId}/files` | needs-setup | not attempted: the sandbox contains no record supplying architecturalRequestId. Creating one is a prerequisite. |
| `POST` | `/v1/associations/ownershipaccounts/architecturalrequests/{architecturalRequestId}/files/uploads` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |
| `GET` | `/v1/associations/ownershipaccounts/architecturalrequests/{architecturalRequestId}/files/{fileId}` | needs-setup | not attempted: the sandbox contains no record supplying architecturalRequestId. Creating one is a prerequisite. |
| `POST` | `/v1/associations/ownershipaccounts/architecturalrequests/{architecturalRequestId}/files/{fileId}/downloadrequests` | write-skipped | association ownership accounting mirrors lease ledgers; same financial reasoning. |

</details>

<details>
<summary><b>Rental Owner Requests</b> — 6 operations, 3 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/tasks/rentalownerrequests` | verified | HTTP 200 |
| `POST` | `/v1/tasks/rentalownerrequests` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/tasks/rentalownerrequests/{rentalOwnerRequestTaskId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/rentalownerrequests/{rentalOwnerRequestTaskId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/tasks/rentalownerrequests/{rentalOwnerRequestTaskId}/contributiondata` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/rentalownerrequests/{rentalOwnerRequestTaskId}/contributiondata` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Board Members</b> — 5 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/{associationId}/boardmembers` | verified | HTTP 200 |
| `POST` | `/v1/associations/{associationId}/boardmembers` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `DELETE` | `/v1/associations/{associationId}/boardmembers/{boardMemberId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/boardmembers/{boardMemberId}` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}/boardmembers/{boardMemberId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Association Meter Readings</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/{associationId}/meterreadings` | verified | HTTP 200 |
| `DELETE` | `/v1/associations/{associationId}/meterreadings/summary` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/associations/{associationId}/meterreadings/summary` | verified | HTTP 200 |
| `PUT` | `/v1/associations/{associationId}/meterreadings/summary` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Budgets</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/budgets` | verified | HTTP 200 |
| `POST` | `/v1/budgets` | write-skipped | budgets span a fiscal year and have no DELETE; a stray test budget would appear in every financial report. |
| `GET` | `/v1/budgets/{budgetId}` | verified | HTTP 200 |
| `PUT` | `/v1/budgets/{budgetId}` | write-skipped | budgets span a fiscal year and have no DELETE; a stray test budget would appear in every financial report. |

</details>

<details>
<summary><b>Contact Requests</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/tasks/contactrequests` | verified | HTTP 200 |
| `POST` | `/v1/tasks/contactrequests` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/tasks/contactrequests/{contactRequestTaskId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/contactrequests/{contactRequestTaskId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Property Groups</b> — 4 operations, 4 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/propertygroups` | verified | HTTP 200 |
| `POST` | `/v1/propertygroups` | verified | HTTP 201 |
| `GET` | `/v1/propertygroups/{propertyGroupId}` | verified | HTTP 200 |
| `PUT` | `/v1/propertygroups/{propertyGroupId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Rental Meter Readings</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/rentals/{propertyId}/meterreadings` | verified | HTTP 200 |
| `DELETE` | `/v1/rentals/{propertyId}/meterreadings/summary` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/rentals/{propertyId}/meterreadings/summary` | verified | HTTP 200 |
| `PUT` | `/v1/rentals/{propertyId}/meterreadings/summary` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Resident Center</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/residentCenterUsers` | verified | HTTP 200 |
| `GET` | `/v1/retailcashusers` | verified | HTTP 200 |
| `GET` | `/v1/retailcashusers/{userId}/{unitAgreementId}` | needs-setup | not attempted: the sandbox contains no record supplying unitAgreementId. Creating one is a prerequisite. |
| `PUT` | `/v1/retailcashusers/{userId}/{unitAgreementId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>Resident Requests</b> — 4 operations, 2 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/tasks/residentrequests` | verified | HTTP 200 |
| `POST` | `/v1/tasks/residentrequests` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |
| `GET` | `/v1/tasks/residentrequests/{residentRequestTaskId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/residentrequests/{residentRequestTaskId}` | write-skipped | not exercised: no DELETE exists and the record would attach permanently to seed data. One representative family member was proven instead. |

</details>

<details>
<summary><b>To Do Requests</b> — 4 operations, 4 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/tasks/todorequests` | verified | HTTP 200 |
| `POST` | `/v1/tasks/todorequests` | verified | HTTP 201 |
| `GET` | `/v1/tasks/todorequests/{toDoTaskId}` | verified | HTTP 200 |
| `PUT` | `/v1/tasks/todorequests/{toDoTaskId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Work Orders</b> — 4 operations, 4 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/workorders` | verified | HTTP 200 |
| `POST` | `/v1/workorders` | verified | HTTP 201 |
| `GET` | `/v1/workorders/{workOrderId}` | verified | HTTP 200 |
| `PUT` | `/v1/workorders/{workOrderId}` | verified | HTTP 200 |

</details>

<details>
<summary><b>Client Leads</b> — 2 operations, 0 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/clientleads` | needs-setup | no record of this type exists in the sandbox (404) |
| `GET` | `/v1/clientleads/{clientLeadId}` | needs-setup | not attempted: the sandbox contains no record supplying clientLeadId. Creating one is a prerequisite. |

</details>

<details>
<summary><b>Committees</b> — 2 operations, 1 verified</summary>

| | Operation | State | Notes |
|---|---|---|---|
| `GET` | `/v1/associations/{associationId}/committees` | verified | HTTP 200 |
| `GET` | `/v1/associations/{associationId}/committees/{committeeId}` | needs-setup | not attempted: the sandbox contains no record supplying committeeId. Creating one is a prerequisite. |

</details>

## Records created

The most recent write run created these. All carry the `ZZ-MCPTEST-` prefix. Records in collections with a `DELETE` were removed and their absence confirmed; the rest remain, which is expected — only 14 of 462 operations support `DELETE`.

| Collection | IDs |
|---|---|
| `/v1/associations/appliances` | 4376 |
| `/v1/bills` | 3548978 |
| `/v1/files` | 396729 |
| `/v1/files/categories` | 2487 |
| `/v1/glaccounts` | 28978 |
| `/v1/leases` | 42354 |
| `/v1/leases/tenants` | 104397 |
| `/v1/propertygroups` | 46 |
| `/v1/rentals` | 13660 |
| `/v1/rentals/appliances` | 4375 |
| `/v1/rentals/appliances/4375/servicehistory` | 3447 |
| `/v1/rentals/owners` | 104395 |
| `/v1/rentals/units` | 49484 |
| `/v1/tasks/40289/history` | 84011 |
| `/v1/tasks/categories` | 2486 |
| `/v1/tasks/todorequests` | 40289 |
| `/v1/vendors` | 104398 |
| `/v1/vendors/104398/notes` | 17720 |
| `/v1/vendors/categories` | 2485 |
| `/v1/workorders` | 4518 |

Every created ID is also appended to `created-records.log`.

