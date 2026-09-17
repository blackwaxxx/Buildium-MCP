"""Derive each evaluation answer from the sandbox snapshot.

Answers in evals/buildium_eval.xml must be computed, not eyeballed. This script
prints the derivation for each so they can be re-checked if sandbox seed data
ever changes.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from buildium_mcp.shaping import is_fixture  # noqa: E402

d = json.loads((ROOT / "sandbox-snapshot.json").read_text())

# Coverage testing leaves permanent records behind — Buildium offers DELETE on
# only 14 of 462 operations — so every count over this sandbox would otherwise
# move each time the write suite runs. The questions ask about the genuine
# portfolio, so the derivation works on the genuine portfolio, and the eval
# questions say so explicitly. buildium_lease_roster and the list tools surface
# the same distinction, so a model can make it too.
PREFIX = "ZZ-MCPTEST-"


def real(records: list) -> list:
    return [r for r in records if not is_fixture(r, PREFIX)]


d = {path: real(records) for path, records in d.items()}

rentals = d["/v1/rentals"]
units = d["/v1/rentals/units"]
leases = d["/v1/leases"]
tenants = d["/v1/leases/tenants"]
owners = d["/v1/rentals/owners"]
gl = d["/v1/glaccounts"]
wos = d["/v1/workorders"]
vendors = d["/v1/vendors"]
banks = d["/v1/bankaccounts"]
assocs = d["/v1/associations"]
appliances = d["/v1/rentals/appliances"]

prop_by_id = {p["Id"]: p for p in rentals}
answers: dict[str, str] = {}


def show(q: str, answer, derivation: str) -> None:
    answers[q] = str(answer)
    print(f"Q{q}: {answer}\n     {derivation}\n")


# 1 — owner holding the most properties -> outdoor appliance -> manufacturer
top_owner = max(owners, key=lambda o: len(o.get("PropertyIds") or []))
owned = set(top_owner["PropertyIds"])
outdoor = [a for a in appliances if a["PropertyId"] in owned and "mower" in a["Name"].lower()]
show("1", outdoor[0]["Make"],
     f"owner {top_owner['FirstName']} {top_owner['LastName']} holds {sorted(owned)}; "
     f"appliance '{outdoor[0]['Name']}' on prop {outdoor[0]['PropertyId']}")

# 2 — the vendor holding the most work orders -> its category
# Originally phrased as "the single vendor on every work order". Write-coverage
# testing added work orders against fixture vendors, so that premise no longer
# holds; "more than any other" survives further test data and gives the same
# answer. The assertion now guards the thing the question depends on — that the
# maximum is not tied.
wo_counts = Counter(w["VendorId"] for w in wos)
top_count = max(wo_counts.values())
leaders = [vid for vid, n in wo_counts.items() if n == top_count]
assert len(leaders) == 1, f"tied for most work orders: {leaders}"
vend = next(v for v in vendors if v["Id"] == leaders[0])
show("2", vend["Category"]["Name"],
     f"vendor {vend['Id']} ({vend['CompanyName']}) holds {top_count} of "
     f"{len(wos)} work orders; runners-up {wo_counts.most_common()[1:]}")

# 3 — the one active lease with zero rent -> tenant full name
zero = [l for l in leases
        if l.get("LeaseStatus") == "Active"
        and (l.get("AccountDetails") or {}).get("Rent") == 0]
assert len(zero) == 1, [l["Id"] for l in zero]
t = next(t for t in tenants if zero[0]["Id"] in [x["Id"] for x in (t.get("Leases") or [])])
show("3", f"{t['FirstName']} {t['LastName']}",
     f"lease {zero[0]['Id']} rent=0 on prop {zero[0]['PropertyId']}")

# 4 — how many leases name more than one tenant
per_lease = defaultdict(list)
for t in tenants:
    for l in t.get("Leases") or []:
        per_lease[l["Id"]].append(f"{t['FirstName']} {t['LastName']}")
multi = {k: v for k, v in per_lease.items() if len(v) > 1}
show("4", len(multi), f"leases with co-tenants: {sorted(multi)}")

# 5 — the city holding only one property
cities = Counter(p["Address"]["City"] for p in rentals)
odd = min(cities.items(), key=lambda kv: kv[1])
show("5", odd[0], f"city counts {dict(cities)}")

# 6 — the non-residential property's tenant
RESIDENTIAL = {"SingleFamily", "MultiFamily", "CondoTownhome"}
non_res = [p for p in rentals if p.get("RentalSubType") not in RESIDENTIAL]
assert len(non_res) == 1, non_res
lease = next(l for l in leases if l["PropertyId"] == non_res[0]["Id"])
name = per_lease[lease["Id"]][0]
show("6", name,
     f"property {non_res[0]['Id']} '{non_res[0]['Name']}' "
     f"subtype={non_res[0]['RentalSubType']}, lease {lease['Id']}")

# 7 — highest active rent at the property with the most units
biggest = max(rentals, key=lambda p: p.get("NumberUnits") or 0)
rents = [(l.get("AccountDetails") or {}).get("Rent")
         for l in leases
         if l["PropertyId"] == biggest["Id"] and l.get("LeaseStatus") == "Active"]
show("7", int(max(r for r in rents if r is not None)),
     f"{biggest['Name']} ({biggest['NumberUnits']} units), active rents {sorted(r for r in rents if r is not None)}")

# 8 — leases with an end date far in the future (2060 placeholder)
far = [l for l in leases if str(l.get("LeaseToDate", "")).startswith("2060")]
show("8", len(far), f"lease ids {[l['Id'] for l in far]}")

# 9 — GL account type (other than Equity) having exactly four accounts
type_counts = Counter(g["Type"] for g in gl)
fours = [t for t, c in type_counts.items() if c == 4 and t != "Equity"]
assert len(fours) == 1, fours
show("9", fours[0], f"type counts {dict(type_counts)}")

# 10 — bank accounts named for the association outside Massachusetts
out_of_state = [a for a in assocs if a["Address"]["State"] != "MA"]
assert len(out_of_state) == 1, out_of_state
token = out_of_state[0]["Name"].split()[0]
matches = [b["Name"] for b in banks if b["Name"].startswith(token)]
show("10", len(matches),
     f"association '{out_of_state[0]['Name']}' ({out_of_state[0]['Address']['State']}) -> {matches}")

print("=" * 60)
print("All answers derived from sandbox-snapshot.json")
(ROOT / "evals").mkdir(exist_ok=True)
(ROOT / "evals" / "derived-answers.json").write_text(json.dumps(answers, indent=2))
print("wrote evals/derived-answers.json")

# Syncing by hand is how a key goes stale: the derivation gets re-run, the
# numbers are read, and one of them does not make it into the XML. --sync
# removes the step that can be forgotten.
XML = ROOT / "evals" / "buildium_eval.xml"


def sync() -> None:
    text = XML.read_text()
    pattern = re.compile(r"<answer>(.*?)</answer>", re.S)
    found = pattern.findall(text)
    if len(found) != len(answers):
        raise SystemExit(
            f"{XML.name} has {len(found)} answers but {len(answers)} were derived. "
            "The question set and the derivation have diverged; fix that by hand."
        )

    changes: list[str] = []
    ordered = [answers[str(i)] for i in range(1, len(answers) + 1)]

    def replace(match, _i=[0]):
        index = _i[0]
        _i[0] += 1
        was, now = match.group(1).strip(), ordered[index]
        if was != now:
            changes.append(f"  Q{index + 1}: {was!r} -> {now!r}")
        return f"<answer>{now}</answer>"

    XML.write_text(pattern.sub(replace, text))
    if changes:
        print(f"\nsynced {XML.name}, {len(changes)} answer(s) changed:")
        print("\n".join(changes))
    else:
        print(f"\n{XML.name} already matches the derivation; nothing to change.")


if "--sync" in sys.argv:
    sync()
else:
    stale = [
        f"Q{i}" for i, (_, derived) in enumerate(sorted(answers.items(), key=lambda kv: int(kv[0])), 1)
        if derived != re.findall(r"<answer>(.*?)</answer>", XML.read_text(), re.S)[i - 1].strip()
    ]
    if stale:
        print(f"\nSTALE: {', '.join(stale)} differ from the XML. "
              "Re-run with --sync to update evals/buildium_eval.xml.")
    else:
        print("\nevals/buildium_eval.xml matches the derivation.")
