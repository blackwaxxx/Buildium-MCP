"""Offline unit tests — no credentials, no network.

Complements tests/stdio_check.py, which needs live sandbox access. These cover
the pure logic: spec indexing, path resolution, response shaping, and the write
guardrails.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from buildium_mcp import config as cfg  # noqa: E402
from buildium_mcp.client import (  # noqa: E402
    BuildiumClient,
    ReadOnlyTransportGuard,
    ReadOnlyViolation,
)
from buildium_mcp.guards import (  # noqa: E402
    FixtureTracker,
    GuardViolation,
    _collect_names,
    _extract_name,
    check_write,
)
from buildium_mcp.shaping import list_result, project  # noqa: E402
from buildium_mcp import client as client_mod  # noqa: E402
from buildium_mcp import paths  # noqa: E402
from buildium_mcp.spec import load_index  # noqa: E402

# Resolve the spec the way the server does, so this exercises real path
# resolution rather than assuming a checkout layout.
SPEC = paths.resolve_spec_path()


@pytest.fixture(scope="module")
def index():
    return load_index(SPEC)


@pytest.fixture
def tracker(tmp_path):
    conf = cfg.Config(
        base_url="https://apisandbox.buildium.com",
        client_id="x",
        client_secret="y",
        spec_path=SPEC,
        run_log=tmp_path / "run.log",
        artifact_log=tmp_path / "artifacts.log",
        fixture_prefix="ZZ-MCPTEST-",
    )
    return FixtureTracker(conf)


# -- spec index --------------------------------------------------------------


def test_every_operation_indexed(index):
    assert len(index.endpoints) == 462


def test_search_ranks_exact_resource_first(index):
    assert index.search("work orders", limit=1)[0].path == "/v1/workorders"


def test_search_respects_method_filter(index):
    assert all(ep.method == "post" for ep in index.search("lease", method="post", limit=10))


def test_search_empty_query_returns_nothing(index):
    assert index.search("") == []


def test_concrete_id_matches_templated_path(index):
    """The bug that made every by-ID call look unknown."""
    resolved = index.resolve_path("GET", "/v1/rentals/appliances/4341")
    assert resolved is not None
    endpoint, request_path = resolved
    assert endpoint.path == "/v1/rentals/appliances/{applianceId}"
    # the CONCRETE path must be what goes on the wire, not the template
    assert request_path == "/v1/rentals/appliances/4341"


def test_missing_v1_prefix_is_tolerated(index):
    resolved = index.resolve_path("GET", "/rentals")
    assert resolved is not None and resolved[0].path == "/v1/rentals"


def test_unknown_path_resolves_to_none(index):
    assert index.resolve_path("GET", "/v1/definitely/not/real") is None


def test_wrong_method_does_not_match(index):
    assert index.resolve_path("DELETE", "/v1/rentals") is None


def test_describe_resolves_refs(index):
    detail = index.describe("POST", "/v1/rentals/appliances")
    schema = detail["requestBody"]["schema"]
    assert "$ref" not in str(schema)[:200]
    assert "PropertyId" in str(schema)


# -- response shaping --------------------------------------------------------


def test_project_drops_unrequested_fields():
    row = {"Id": 1, "Name": "x", "TaxPayerId": "123-45-6789"}
    assert project(row, ["Id", "Name"]) == {"Id": 1, "Name": "x"}


def test_project_without_fields_is_identity():
    row = {"Id": 1, "TaxPayerId": "secret"}
    assert project(row, None) == row


def test_project_maps_over_lists():
    rows = [{"Id": 1, "X": 9}, {"Id": 2, "X": 9}]
    assert project(rows, ["Id"]) == [{"Id": 1}, {"Id": 2}]


def test_full_page_signals_more():
    res = list_result([{"Id": i} for i in range(5)], limit=5, offset=10)
    assert res["has_more"] is True
    assert res["next_offset"] == 15


def test_partial_page_signals_end():
    res = list_result([{"Id": 1}], limit=50, offset=0)
    assert res["has_more"] is False
    assert res["next_offset"] is None


# -- write guardrails --------------------------------------------------------


def test_reads_are_never_blocked(tracker):
    check_write("GET", "/v1/rentals/1", None, tracker)  # must not raise


def test_create_requires_fixture_prefix(tracker):
    with pytest.raises(GuardViolation, match="must start with"):
        check_write("POST", "/v1/rentals/appliances", {"Name": "Fridge"}, tracker)


def test_create_with_prefix_allowed(tracker):
    check_write("POST", "/v1/rentals/appliances", {"Name": "ZZ-MCPTEST-Fridge"}, tracker)


def test_delete_requires_confirm(tracker):
    with pytest.raises(GuardViolation, match="confirm"):
        check_write("DELETE", "/v1/rentals/appliances/1", None, tracker)


def test_delete_of_unowned_record_refused(tracker):
    with pytest.raises(GuardViolation, match="did not create"):
        check_write("DELETE", "/v1/rentals/appliances/1", None, tracker, confirm=True)


def test_update_of_unowned_record_refused(tracker):
    with pytest.raises(GuardViolation, match="did not create"):
        check_write("PUT", "/v1/rentals/appliances/1", {"Name": "ZZ-MCPTEST-x"}, tracker)


def test_owned_record_may_be_updated_and_deleted(tracker):
    tracker.record("/v1/rentals/appliances", 4242, {"Name": "ZZ-MCPTEST-x"})
    check_write("PUT", "/v1/rentals/appliances/4242", {"Name": "ZZ-MCPTEST-y"}, tracker)
    check_write("DELETE", "/v1/rentals/appliances/4242", None, tracker, confirm=True)


def test_ownership_does_not_leak_across_collections(tracker):
    """Creating appliance 5 must not authorize deleting vendor 5."""
    tracker.record("/v1/rentals/appliances", 5, {"Name": "ZZ-MCPTEST-x"})
    with pytest.raises(GuardViolation, match="did not create"):
        check_write("DELETE", "/v1/vendors/5", None, tracker, confirm=True)


def test_open_mode_lifts_fixture_rules(tracker, monkeypatch):
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "open")
    check_write("POST", "/v1/rentals/appliances", {"Name": "Real Fridge"}, tracker)
    check_write("PUT", "/v1/rentals/appliances/999", {"Name": "Real"}, tracker)


def test_open_mode_still_requires_delete_confirm(tracker, monkeypatch):
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "open")
    with pytest.raises(GuardViolation, match="confirm"):
        check_write("DELETE", "/v1/rentals/appliances/999", None, tracker)


def test_unknown_write_mode_falls_back_to_safe(tracker, monkeypatch):
    """A typo in the env var must not silently disable the guardrails."""
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "opne")
    with pytest.raises(GuardViolation, match="must start with"):
        check_write("POST", "/v1/rentals/appliances", {"Name": "Fridge"}, tracker)


# -- nameless payloads -------------------------------------------------------
#
# 84 of the 119 POST endpoints in the spec have no Name/Title/Subject/
# CategoryName/FirstName anywhere in their request body: charges, payments,
# journal entries, checks, deposits, notes. The prefix check cannot fire on
# them, so what it means to be in 'fixtures' mode on those endpoints is decided
# by where the record would land.

PAYMENT = {"Amount": 1, "EntryDate": "2026-01-01", "PaymentMethod": "Check"}


def test_nameless_create_allowed_against_the_sandbox(tracker):
    """Sandbox data is disposable, so an untaggable create is harmless."""
    check_write("POST", "/v1/leases/1/payments", PAYMENT, tracker)


def test_nameless_create_refused_against_production(tmp_path):
    """The gap this closes: fixtures mode is the default, so an operator who
    sets production-write and leaves the write mode alone must not silently
    create live untagged records."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    with pytest.raises(GuardViolation, match="no name field"):
        check_write("POST", "/v1/leases/1/payments", PAYMENT, t)


def test_nameless_create_refusal_names_the_host(tmp_path):
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    with pytest.raises(GuardViolation, match="api.buildium.com"):
        check_write("POST", "/v1/generalledger/journalentries", {"Lines": []}, t)


def test_production_mode_pointed_at_the_sandbox_still_allows_it(tmp_path):
    """Mode says what is permitted; the base URL says what is targeted. A
    production-write server aimed at the sandbox is still writing to the
    sandbox, and the write-coverage suite depends on exactly this."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE))
    check_write("POST", "/v1/leases/1/payments", PAYMENT, t)


def test_open_mode_still_permits_nameless_production_creates(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "open")
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    check_write("POST", "/v1/leases/1/payments", PAYMENT, t)


def test_download_request_survives_the_nameless_rule(tmp_path):
    """A download request is a POST with no body that creates nothing. The
    read-only modes carve it out already; production-write reaches the POST
    branch, where it would otherwise be refused for having no name."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    check_write("POST", "/v1/files/5/downloadrequest", None, t)
    check_write("POST", "/v1/rentals/7/images/9/downloadrequests", {}, t)


def test_a_nameless_production_create_is_still_refused_near_a_download_path(tmp_path):
    """The carve-out is the seven templates, not anything download-shaped."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    with pytest.raises(GuardViolation, match="no name field"):
        check_write("POST", "/v1/files/5/downloadrequest/extra", None, t)


# -- nested names ------------------------------------------------------------
#
# Creating a lease creates its tenants. A top-level-only scan saw no name on
# that payload and let the whole thing through, live tenants included.

def _lease(*first_names):
    return {
        "UnitId": 1,
        "LeaseType": "AtWill",
        "Tenants": [{"FirstName": n, "LastName": "Fixture"} for n in first_names],
    }


def test_nested_tenant_name_must_carry_the_prefix(tracker):
    with pytest.raises(GuardViolation, match=r"Tenants\[0\]\.FirstName"):
        check_write("POST", "/v1/leases", _lease("Dana"), tracker)


def test_nested_tenant_name_with_the_prefix_is_allowed(tracker):
    check_write("POST", "/v1/leases", _lease("ZZ-MCPTEST-Dana"), tracker)


def test_every_nested_name_is_checked_not_only_the_first(tracker):
    """One prefixed tenant must not license an unprefixed one beside it."""
    with pytest.raises(GuardViolation, match=r"Tenants\[1\]\.FirstName"):
        check_write("POST", "/v1/leases",
                    _lease("ZZ-MCPTEST-Dana", "Rui"), tracker)


def test_deeply_nested_name_is_found(tracker):
    body = {"Tenants": [{"FirstName": "ZZ-MCPTEST-Dana",
                         "EmergencyContact": {"Name": "Rui"}}]}
    with pytest.raises(GuardViolation, match=r"EmergencyContact\.Name"):
        check_write("POST", "/v1/leases", body, tracker)


def test_a_nested_name_counts_as_a_name_for_the_production_rule(tmp_path):
    """Having found a name, the nameless rule must not also fire."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    check_write("POST", "/v1/leases", _lease("ZZ-MCPTEST-Dana"), t)


def test_collect_names_reports_top_level_before_nested():
    names, truncated = _collect_names({"Name": "outer", "Child": {"Name": "inner"}})
    assert names == [("Name", "outer"), ("Child.Name", "inner")]
    assert truncated is False


def test_extract_name_still_prefers_the_records_own_label():
    """The artifact log wants the record's name, not a passenger's."""
    assert _extract_name({"Name": "outer", "Child": {"Name": "inner"}}) == "outer"


def test_extract_name_now_finds_a_nested_label_where_there_was_none():
    assert _extract_name(_lease("ZZ-MCPTEST-Dana")) == "ZZ-MCPTEST-Dana"


def test_name_fields_are_ranked_within_a_node():
    assert _extract_name({"Title": "t", "Name": "n"}) == "n"


def test_empty_and_non_string_names_are_ignored():
    assert _collect_names({"Name": "", "Title": 5, "Subject": None}) == ([], False)


def _buried(depth):
    """A name `depth` levels down, past the scan's limit when depth is large."""
    body = node = {}
    for _ in range(depth):
        node["Child"] = {}
        node = node["Child"]
    node["Name"] = "buried"
    return body


def test_the_deepest_real_payload_shape_is_not_truncated():
    """/v1/bills/payments is the deepest nesting in the spec. If a real payload
    ever read as truncated, the fail-closed rule would refuse a valid
    production write."""
    body = {
        "Lines": [{
            "AccountingEntity": {"Id": 1, "AccountingEntityType": "Rental",
                                 "Unit": {"Id": 2, "Href": "x"}},
            "Amount": 1,
        }],
    }
    names, truncated = _collect_names(body)
    assert truncated is False
    assert names == []


def test_name_scan_is_depth_bounded():
    names, truncated = _collect_names(_buried(12))
    assert names == []
    assert truncated is True


def test_name_scan_is_breadth_bounded():
    """A huge payload must not turn the guard into an unbounded traversal."""
    body = {"Lines": [{"Memo": str(i)} for i in range(5000)]}
    names, truncated = _collect_names(body)
    assert names == []
    assert truncated is True


def test_a_payload_too_big_to_check_is_refused_against_production(tmp_path):
    """Truncation means 'unknown', not 'clean'. Burying an unprefixed name
    past the cap must not be a way through the check."""
    t = FixtureTracker(_conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                             base_url="https://api.buildium.com"))
    with pytest.raises(GuardViolation, match="too large or deeply nested"):
        check_write("POST", "/v1/leases", _buried(12), t)


def test_a_payload_too_big_to_check_is_still_fine_against_the_sandbox(tracker):
    check_write("POST", "/v1/leases", _buried(12), tracker)


def test_truncation_does_not_hide_a_name_the_scan_did_reach(tracker):
    body = _buried(12)
    body["Name"] = "Real"
    with pytest.raises(GuardViolation, match="must start with"):
        check_write("POST", "/v1/leases", body, tracker)


def test_name_scan_tolerates_a_non_dict_body():
    assert _collect_names(None) == ([], False)
    assert _collect_names("a string") == ([], False)
    assert _collect_names([{"Name": "ZZ-MCPTEST-x"}]) == (
        [("[0].Name", "ZZ-MCPTEST-x")], False,
    )


# -- production hard-block ---------------------------------------------------


def test_production_host_refused(monkeypatch):
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://api.buildium.com")
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    with pytest.raises(cfg.ConfigError, match="production"):
        cfg.load_config()


def test_unrecognized_host_refused(monkeypatch):
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://evil.example.com")
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    with pytest.raises(cfg.ConfigError, match="unrecognized host"):
        cfg.load_config()


def test_sandbox_is_the_default_everywhere(monkeypatch):
    """Tripwire: the safe mode must be what you get by doing nothing.

    Two independent defaults, because a regression in either would ship a
    production-capable server to someone who never asked for one: the dataclass
    field, and what load_config() returns with a clean environment.
    """
    assert cfg.Config.__dataclass_fields__["mode"].default is cfg.DeploymentMode.SANDBOX

    monkeypatch.delenv(cfg.MODE_ENV_VAR, raising=False)
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode.SANDBOX
    assert conf.mode_source == "default"


# -- the four deployment states ----------------------------------------------
#
# Each state is selected the way a real operator selects one: by setting
# BUILDIUM_DEPLOYMENT_MODE. The tests assert both what each state permits and
# that no *other* environment variable can move a server between states.


@pytest.fixture
def mode(monkeypatch):
    """Select a mode the way an operator does — through the env var."""

    def _set(value: cfg.DeploymentMode):
        monkeypatch.setenv(cfg.MODE_ENV_VAR, value.value)
        monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
        monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")

    return _set


def _conf(tmp_path, deployment_mode, base_url="https://apisandbox.buildium.com"):
    return cfg.Config(
        base_url=base_url,
        client_id="x",
        client_secret="y",
        spec_path=SPEC,
        run_log=tmp_path / "run.log",
        artifact_log=tmp_path / "artifacts.log",
        fixture_prefix="ZZ-MCPTEST-",
        mode=deployment_mode,
    )


# state 1: sandbox

def test_sandbox_mode_accepts_sandbox_host(mode):
    mode(cfg.DeploymentMode.SANDBOX)
    monkey = cfg.load_config()
    assert monkey.mode is cfg.DeploymentMode.SANDBOX
    assert monkey.writes_allowed is True
    assert monkey.environment == "sandbox"


def test_sandbox_mode_refuses_production_host(mode, monkeypatch):
    mode(cfg.DeploymentMode.SANDBOX)
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://api.buildium.com")
    with pytest.raises(cfg.ConfigError, match="production host"):
        cfg.load_config()


def test_sandbox_mode_permits_writes(tmp_path):
    conf = _conf(tmp_path, cfg.DeploymentMode.SANDBOX)
    t = FixtureTracker(conf)
    # A correctly prefixed create passes; the fixture guard is the only gate.
    check_write("POST", "/v1/rentals/appliances", {"Name": "ZZ-MCPTEST-x"}, t)


# state 2: production-readonly

def test_production_readonly_accepts_production_host(mode, monkeypatch):
    mode(cfg.DeploymentMode.PRODUCTION_READONLY)
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://api.buildium.com")
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode.PRODUCTION_READONLY
    assert conf.writes_allowed is False
    assert "read-only" in conf.environment


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_production_readonly_refuses_every_mutating_method(tmp_path, method):
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_READONLY)
    t = FixtureTracker(conf)
    # Even a record this process created, even with confirm, even correctly
    # prefixed — the deployment mode outranks all of it.
    t.record("/v1/rentals/appliances/5", 5)
    with pytest.raises(GuardViolation, match="production-readonly"):
        check_write(method, "/v1/rentals/appliances/5",
                    {"Name": "ZZ-MCPTEST-x"}, t, confirm=True)


def test_production_readonly_still_allows_reads(tmp_path):
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_READONLY)
    check_write("GET", "/v1/leases", None, FixtureTracker(conf))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_production_readonly_blocks_at_transport_layer(tmp_path, method):
    """The structural claim: mutation dies before a socket is opened.

    This bypasses BuildiumClient.request and the guards entirely, calling the
    underlying httpx client directly — the thing an agent would reach for if it
    were trying to route around the policy check.
    """
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_READONLY)
    client = BuildiumClient(conf)
    try:
        with pytest.raises(ReadOnlyViolation):
            await client._client.request(method, "/v1/rentals/appliances", json={})
    finally:
        await client.aclose()


async def test_production_readonly_transport_permits_get(tmp_path):
    """The guard must not be a blanket network block — GET still reaches httpx.

    The guard's inner transport is swapped for a stub, so "reached httpx" is
    observed as the stub's 200 coming back through the guard. Nothing leaves
    the machine.
    """
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_READONLY,
                 base_url="https://apisandbox.buildium.com")
    client = BuildiumClient(conf)
    guard = client._client._transport
    assert isinstance(guard, ReadOnlyTransportGuard)
    req = httpx.Request("GET", "https://apisandbox.buildium.com/v1/leases")
    # Swap the inner transport for a stub so no real request leaves the machine.
    guard._inner = _StubTransport()
    resp = await guard.handle_async_request(req)
    assert resp.status_code == 200
    await client.aclose()


class _StubTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        return httpx.Response(200, json=[])

    async def aclose(self):
        return None


async def test_sandbox_mode_installs_no_transport_guard(tmp_path):
    conf = _conf(tmp_path, cfg.DeploymentMode.SANDBOX)
    client = BuildiumClient(conf)
    assert not isinstance(client._client._transport, ReadOnlyTransportGuard)
    await client.aclose()


# state 3: production-write

def test_production_write_accepts_production_host(mode, monkeypatch):
    mode(cfg.DeploymentMode.PRODUCTION_WRITE)
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://api.buildium.com")
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode.PRODUCTION_WRITE
    assert conf.writes_allowed is True
    assert "writes enabled" in conf.environment


def test_production_write_permits_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "open")
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE,
                 base_url="https://api.buildium.com")
    check_write("PUT", "/v1/leases/9", {"Name": "real"}, FixtureTracker(conf))


def test_every_mode_still_refuses_an_unknown_host(mode, monkeypatch):
    """Widening the mode must not widen the host allowlist."""
    monkeypatch.setenv("BUILDIUM_BASE_URL", "https://evil.example.com")
    for value in cfg.DeploymentMode:
        mode(value)
        with pytest.raises(cfg.ConfigError, match="unrecognized host"):
            cfg.load_config()


# -- exactly one environment variable may change the deployment mode ---------
#
# This section used to prove the mode was *unreachable* from the environment.
# Publishing the server made that untenable: a pip-installed user cannot edit a
# constant inside site-packages. The guarantee is now three narrower claims,
# and each gets a test: the default is safe, exactly one variable moves it, and
# an unrecognized value stops the server rather than being quietly reinterpreted.

# Every name an agent or a misconfigured launcher might plausibly reach for.
OVERRIDE_ATTEMPTS = [
    "DEPLOYMENT_MODE",
    "BUILDIUM_DEPLOYMENT_MODE",
    "BUILDIUM_MODE",
    "BUILDIUM_ENV",
    "BUILDIUM_ENVIRONMENT",
    "ALLOW_PRODUCTION",
    "BUILDIUM_ALLOW_PRODUCTION",
    "BUILDIUM_PRODUCTION",
    "BUILDIUM_WRITES_ALLOWED",
    "BUILDIUM_READONLY",
    "BUILDIUM_READ_ONLY",
    "BUILDIUM_UNSAFE",
    "BUILDIUM_FORCE",
]

# All of the above except the one real knob. These must remain inert.
DECOY_ENV_VARS = [n for n in OVERRIDE_ATTEMPTS if n != cfg.MODE_ENV_VAR]


@pytest.fixture
def clean_mode_env(monkeypatch):
    for name in OVERRIDE_ATTEMPTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    return monkeypatch


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_empty_or_whitespace_is_treated_as_unset(clean_mode_env, raw):
    """A client emitting an empty env value must neither escalate nor crash."""
    clean_mode_env.setenv(cfg.MODE_ENV_VAR, raw)
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode.SANDBOX
    assert conf.mode_source == "default"


@pytest.mark.parametrize("var", DECOY_ENV_VARS)
@pytest.mark.parametrize("value", ["production-write", "true", "1", "PRODUCTION_WRITE"])
def test_no_decoy_env_var_can_widen_the_mode(clean_mode_env, var, value):
    clean_mode_env.setenv(var, value)
    assert cfg.load_config().mode is cfg.DeploymentMode.SANDBOX
    # and the production host is still refused
    clean_mode_env.setenv("BUILDIUM_BASE_URL", "https://api.buildium.com")
    with pytest.raises(cfg.ConfigError):
        cfg.load_config()


def test_no_decoy_env_var_can_narrow_the_mode_either(clean_mode_env):
    """Symmetry: a stray env var must not silently downgrade a deliberate
    production-write deployment into read-only, which would look like an
    outage rather than a policy."""
    clean_mode_env.setenv(cfg.MODE_ENV_VAR, "production-write")
    for var in DECOY_ENV_VARS:
        clean_mode_env.setenv(var, "production-readonly")
    assert cfg.load_config().mode is cfg.DeploymentMode.PRODUCTION_WRITE


@pytest.mark.parametrize("mode_value", [m.value for m in cfg.DeploymentMode])
def test_the_real_env_var_selects_each_mode(clean_mode_env, mode_value):
    clean_mode_env.setenv(cfg.MODE_ENV_VAR, mode_value)
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode(mode_value)
    assert conf.mode_source == cfg.MODE_ENV_VAR


@pytest.mark.parametrize("raw,expected", [
    ("SANDBOX", cfg.DeploymentMode.SANDBOX),
    ("Production-ReadOnly", cfg.DeploymentMode.PRODUCTION_READONLY),
    ("production_write", cfg.DeploymentMode.PRODUCTION_WRITE),
    ("  production-readonly-files  ", cfg.DeploymentMode.PRODUCTION_READONLY_FILES),
    ("PRODUCTION_READONLY_FILES", cfg.DeploymentMode.PRODUCTION_READONLY_FILES),
])
def test_mode_values_are_case_and_underscore_insensitive(raw, expected):
    """Pin exactly how forgiving the parser is, so nothing broader creeps in."""
    assert cfg.parse_deployment_mode(raw)[0] is expected


@pytest.mark.parametrize("raw", [
    "prod", "production", "production-writes", "write", "readonly",
    "true", "1", "yes", "on",
    "PRODUCTION-WRITE!", "sandbox production-write",
    "production-readonly-file", "production-readonly-filess",
    "../production-write", "production-write;sandbox",
    "production write", "-production-write",
])
def test_unrecognized_mode_value_is_a_hard_error(raw):
    """A typo must stop the server, not silently pick a mode.

    Falling back to sandbox would be *safe* but looks like an outage, and the
    instinctive fix for an outage is to escalate. Failing loudly is safer than
    failing quietly in the direction of least privilege.
    """
    with pytest.raises(cfg.ConfigError) as exc:
        cfg.parse_deployment_mode(raw)
    message = str(exc.value)
    for m in cfg.DeploymentMode:
        assert m.value in message, "the error must list every valid value"


# Environment variables that legitimately contain a mode-like word. Exactly
# these two may be read anywhere in the package: the deployment-mode knob, and
# the write-mode knob, which can only narrow what the deployment mode allows.
_PERMITTED_MODE_LIKE_ENV_VARS = {cfg.MODE_ENV_VAR, "BUILDIUM_WRITE_MODE"}


def test_package_reads_exactly_one_deployment_mode_env_var():
    """Source-level proof, stronger than the behavioural tests above.

    Fails in both directions: if the one legitimate variable is removed, and if
    a second backdoor is ever added — in *any* module of the package, not just
    config.py, since a read in runtime.py or paths.py would be just as much a
    backdoor. Resolves module constants as well as string literals, so routing
    a read through a name cannot hide it, and matches os.environ[...] /
    os.environ.get(...) as well as os.getenv(...).
    """
    import ast

    package = ROOT / "src" / "buildium_mcp"
    trees = {
        path.name: ast.parse(path.read_text())
        for path in sorted(package.glob("*.py"))
    }
    assert "config.py" in trees and "runtime.py" in trees and "guards.py" in trees

    # Module-level NAME = "literal" in any module, so a read through a constant
    # resolves — including a constant imported from config.py.
    constants: dict[str, str] = {}
    for tree in trees.values():
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = node.value.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
                if isinstance(node.target, ast.Name) and isinstance(node.value.value, str):
                    constants[node.target.id] = node.value.value

    def resolve(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    names: list[str] = []
    for tree in trees.values():
        for node in ast.walk(tree):
            arg = None
            if isinstance(node, ast.Call) and node.args:
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("getenv", "get"):
                    arg = node.args[0]
            elif isinstance(node, ast.Subscript):
                value = node.value
                if isinstance(value, ast.Attribute) and value.attr == "environ":
                    arg = node.slice
            if arg is not None:
                resolved = resolve(arg)
                if resolved:
                    names.append(resolved)

    assert cfg.MODE_ENV_VAR in names, "the one legitimate read has gone missing"
    mode_like = {
        name for name in names
        if any(word in name for word in
               ("MODE", "PROD", "ALLOW", "READONLY", "UNSAFE", "FORCE", "WRITE"))
    }
    assert mode_like == _PERMITTED_MODE_LIKE_ENV_VARS, (
        f"the package should read exactly {sorted(_PERMITTED_MODE_LIKE_ENV_VARS)}, "
        f"found: {sorted(mode_like)}"
    )


def test_production_mode_alone_does_not_change_the_base_url(clean_mode_env):
    """The env var widens *permission*, never *target*.

    This is the two-factor property that survives from the old design: reaching
    production still takes a deliberate BUILDIUM_BASE_URL as well.
    """
    clean_mode_env.delenv("BUILDIUM_BASE_URL", raising=False)
    clean_mode_env.setenv(cfg.MODE_ENV_VAR, "production-write")
    conf = cfg.load_config()
    assert conf.mode is cfg.DeploymentMode.PRODUCTION_WRITE
    assert conf.is_sandbox
    assert conf.host in cfg.SANDBOX_HOSTS


# -- allOf flattening --------------------------------------------------------


def test_request_body_required_fields_are_visible(index):
    """Every request body in this spec is wrapped as {"allOf": [{"$ref": ...}]}.

    Unflattened, describe_endpoint hands a model a top-level schema with no
    'required' and no 'properties', which reads as "send whatever you like".
    """
    schema = index.describe("POST", "/v1/rentals/appliances")["requestBody"]["schema"]
    assert schema["required"] == ["Name", "PropertyId"]
    assert "PropertyId" in schema["properties"]
    assert "allOf" not in schema


def test_flatten_merges_multiple_members():
    from buildium_mcp.spec import _flatten_all_of

    merged = _flatten_all_of({
        "allOf": [
            {"properties": {"A": {"type": "string"}}, "required": ["A"]},
            {"properties": {"B": {"type": "integer"}}, "required": ["B"]},
        ]
    })
    assert merged["required"] == ["A", "B"]
    assert set(merged["properties"]) == {"A", "B"}


def test_flatten_leaves_genuine_alternatives_alone():
    """oneOf/anyOf express a choice; merging them would invent a schema that
    permits combinations the API rejects."""
    from buildium_mcp.spec import _flatten_all_of

    node = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    assert _flatten_all_of(node) == node
    composed = {"allOf": [{"oneOf": [{"type": "string"}]}]}
    assert "allOf" in _flatten_all_of(composed)


def test_every_post_body_now_exposes_its_schema(index):
    """Regression net: no POST should present an opaque body."""
    opaque = []
    for ep in index.endpoints:
        if ep.method != "post":
            continue
        detail = index.describe(ep.method, ep.path)
        body = (detail or {}).get("requestBody")
        if not body or not body.get("schema"):
            continue
        schema = body["schema"]
        if "allOf" in schema and "properties" not in schema:
            opaque.append(ep.path)
    assert opaque == [], f"{len(opaque)} POST bodies still hide their fields"


# -- auto-pagination ---------------------------------------------------------


class _PagingTransport(httpx.AsyncBaseTransport):
    """Serves a fixed-size collection with Buildium's offset/limit semantics."""

    def __init__(self, total: int):
        self.total = total
        self.requests: list[tuple[int, int]] = []

    async def handle_async_request(self, request):
        params = dict(request.url.params)
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        self.requests.append((limit, offset))
        page = [{"Id": i} for i in range(offset, min(offset + limit, self.total))]
        return httpx.Response(200, json=page)

    async def aclose(self):
        return None


def _paging_client(tmp_path, total):
    conf = _conf(tmp_path, cfg.DeploymentMode.SANDBOX)
    client = BuildiumClient(conf)
    transport = _PagingTransport(total)
    client._client = httpx.AsyncClient(
        transport=transport, base_url="https://apisandbox.buildium.com"
    )
    return client, transport


async def test_auto_paginate_follows_to_completion(tmp_path):
    client, transport = _paging_client(tmp_path, 250)
    records, truncated = await client.get_all_pages("/v1/leases", page_size=100)
    assert len(records) == 250
    assert truncated is False
    assert [r["Id"] for r in records] == list(range(250))
    await client.aclose()


async def test_auto_paginate_costs_one_extra_request_on_exact_multiple(tmp_path):
    """A short page is the only end-of-collection signal Buildium gives, so an
    exact multiple of the page size needs one more request to confirm. Stopping
    early instead would silently under-count."""
    client, transport = _paging_client(tmp_path, 200)
    records, truncated = await client.get_all_pages("/v1/leases", page_size=100)
    assert len(records) == 200 and truncated is False
    assert transport.requests == [(100, 0), (100, 100), (100, 200)]
    await client.aclose()


async def test_auto_paginate_reports_truncation_honestly(tmp_path):
    client, _ = _paging_client(tmp_path, 500)
    records, truncated = await client.get_all_pages(
        "/v1/leases", page_size=50, max_records=120
    )
    assert len(records) == 120
    assert truncated is True, "a partial answer must say so"
    await client.aclose()


async def test_auto_paginate_does_not_claim_truncation_at_an_exact_cap(tmp_path):
    """Exactly max_records available is complete, not truncated."""
    client, _ = _paging_client(tmp_path, 100)
    records, truncated = await client.get_all_pages(
        "/v1/leases", page_size=50, max_records=100
    )
    assert len(records) == 100 and truncated is False
    await client.aclose()


async def test_auto_paginate_handles_an_empty_collection(tmp_path):
    client, _ = _paging_client(tmp_path, 0)
    records, truncated = await client.get_all_pages("/v1/leases")
    assert records == [] and truncated is False
    await client.aclose()


# -- error hints -------------------------------------------------------------


def _translate(status, payload, path="/v1/bills"):
    from buildium_mcp.client import BuildiumClient

    conf = cfg.Config(
        base_url="https://apisandbox.buildium.com", client_id="x", client_secret="y",
        spec_path=SPEC, run_log=Path("/dev/null"), artifact_log=Path("/dev/null"),
        fixture_prefix="ZZ-MCPTEST-",
    )
    return str(BuildiumClient._translate(
        BuildiumClient.__new__(BuildiumClient), status, payload, "GET", path
    ))


def test_bills_hint_names_the_parameters_the_api_actually_wants():
    """The original hint suggested entityid/entitytype or 'a date range'. The
    API wants frompaiddate AND topaiddate; following the old hint still 422s."""
    message = _translate(422, {"UserMessage": "failed",
                               "Errors": [{"Key": "FromPaidDate", "Value": "required"}]})
    assert "frompaiddate" in message and "topaiddate" in message
    assert "entityid" not in message


def test_date_range_cap_is_explained_wherever_it_fires():
    """The cap applies to nine endpoints, so the hint keys off the message
    rather than the path."""
    message = _translate(
        422,
        {"UserMessage": "failed",
         "Errors": [{"Key": "StartDate",
                     "Value": "The time range must be less than or equal to 365 days."}]},
        path="/v1/bankaccounts/1/transactions",
    )
    assert "365 days" in message
    assert "year or less" in message


def test_unrelated_422_gets_no_spurious_hint():
    message = _translate(422, {"UserMessage": "nope", "Errors": []},
                         path="/v1/rentals")
    assert "365 days" not in message
    assert "Hint:" not in message


# -- the evaluation file -----------------------------------------------------


def test_eval_xml_is_well_formed():
    """A malformed eval file does not fail loudly.

    The harness reports "Loaded 0 evaluation tasks", writes a report, and exits
    zero — a run that proves nothing looks like a run that passed. This caught
    a real instance: a double hyphen inside an XML comment, which is illegal,
    introduced while documenting a command-line flag.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(ROOT / "evals" / "buildium_eval.xml").getroot()
    pairs = root.findall("qa_pair")
    assert len(pairs) == 10, f"expected 10 eval tasks, found {len(pairs)}"
    for pair in pairs:
        assert (pair.findtext("question") or "").strip()
        assert (pair.findtext("answer") or "").strip()


def test_eval_answers_match_the_derivation():
    """The XML must agree with evals/derived-answers.json.

    Answers are counts over live sandbox data and drift whenever anything is
    written. This does not re-derive — that needs network — it only asserts the
    two committed files agree, so a derivation that was run but never synced
    fails here instead of surfacing as ten false eval failures.
    """
    import json as _json
    import xml.etree.ElementTree as ET

    derived = _json.loads((ROOT / "evals" / "derived-answers.json").read_text())
    root = ET.parse(ROOT / "evals" / "buildium_eval.xml").getroot()
    in_xml = [(p.findtext("answer") or "").strip() for p in root.findall("qa_pair")]
    expected = [derived[str(i)] for i in range(1, len(in_xml) + 1)]
    assert in_xml == expected, (
        "evals/buildium_eval.xml is out of sync with the derivation; "
        "run tests/verify_eval_answers.py with --sync"
    )


# -- deprecation -------------------------------------------------------------


def test_deprecated_operations_are_flagged(index):
    """16 operations start returning 410 Gone on 2026-10-19. That fact lives in
    prose in the spec's description, where a model choosing between search
    results will not see it."""
    deprecated = [ep for ep in index.endpoints if ep.deprecated]
    assert len(deprecated) == 16
    brief = index.get("get", "/v1/rentals/appliances").brief()
    assert brief["deprecated"] is True
    assert "410 Gone" in brief["deprecation_notice"]
    assert "2026-10-19" in brief["deprecation_notice"]
    assert "/v1/inventoryassets" in brief["deprecation_notice"]


def test_live_endpoints_are_not_labelled_deprecated(index):
    assert "deprecated" not in index.get("get", "/v1/leases").brief()
    assert index.describe("GET", "/v1/leases")["deprecated"] is False


def test_deprecated_endpoints_rank_below_equivalent_live_ones(index):
    """They still appear — until Buildium migrates the data, the deprecated
    endpoint is often the only one holding records — but never above a live
    endpoint that matched equally well."""
    results = index.search("inventory assets", limit=10)
    live = [i for i, ep in enumerate(results) if not ep.deprecated]
    dead = [i for i, ep in enumerate(results) if ep.deprecated]
    if live and dead:
        assert min(live) < min(dead)


# -- fixture awareness -------------------------------------------------------
#
# Buildium offers DELETE on 14 of 462 operations, so any account that has been
# tested against accumulates test records permanently. That makes every count
# ambiguous. These tests pin the behaviour that makes the ambiguity visible
# rather than silent — an evaluating model counted 6 co-tenant leases, decided
# 3 of them were fixtures, and answered 3 without anything in the response
# telling it that judgement was needed.


def test_is_fixture_checks_every_name_field():
    from buildium_mcp.shaping import is_fixture

    assert is_fixture({"Name": "ZZ-MCPTEST-x"}, "ZZ-MCPTEST-")
    assert is_fixture({"CompanyName": "ZZ-MCPTEST-vendor"}, "ZZ-MCPTEST-")
    assert is_fixture({"FirstName": "ZZ-MCPTEST-tenant"}, "ZZ-MCPTEST-")
    assert not is_fixture({"Name": "74 Grove Street"}, "ZZ-MCPTEST-")
    assert not is_fixture({"Description": "ZZ-MCPTEST- mentioned"}, "ZZ-MCPTEST-")


def test_is_fixture_is_inert_without_a_prefix():
    """An empty prefix must not classify every record as a fixture."""
    from buildium_mcp.shaping import is_fixture

    assert not is_fixture({"Name": "anything"}, "")


def test_list_result_reports_fixtures_without_being_asked():
    rows = [{"Name": "Real One"}, {"Name": "ZZ-MCPTEST-two"}]
    out = list_result(rows, 50, 0, fixture_prefix="ZZ-MCPTEST-")
    assert out["count"] == 2, "nothing is dropped unless asked"
    assert out["fixture_count"] == 1
    assert "exclude_fixtures" in out["fixture_note"]


def test_list_result_stays_quiet_when_there_are_no_fixtures():
    out = list_result([{"Name": "Real"}], 50, 0, fixture_prefix="ZZ-MCPTEST-")
    assert "fixture_count" not in out and "fixture_note" not in out


def test_list_result_can_exclude_fixtures():
    rows = [{"Name": "Real"}, {"Name": "ZZ-MCPTEST-two"}]
    out = list_result(rows, 50, 0, fixture_prefix="ZZ-MCPTEST-",
                      exclude_fixtures=True)
    assert out["count"] == 1
    assert out["data"] == [{"Name": "Real"}]
    assert out["fixtures_excluded"] is True


def test_excluding_fixtures_does_not_disturb_pagination():
    """next_offset must keep counting the records the server actually returned,
    or the next page silently skips whatever was filtered out."""
    rows = [{"Name": f"ZZ-MCPTEST-{i}" if i % 2 else f"Real {i}"} for i in range(10)]
    out = list_result(rows, 10, 0, fixture_prefix="ZZ-MCPTEST-",
                      exclude_fixtures=True)
    assert out["count"] == 5
    assert out["next_offset"] == 10, "offset tracks the server's rows, not ours"


def test_split_fixtures_partitions_without_loss():
    from buildium_mcp.shaping import split_fixtures

    rows = [{"Name": "a"}, {"Name": "ZZ-MCPTEST-b"}, {"Name": "c"}]
    real, fixtures = split_fixtures(rows, "ZZ-MCPTEST-")
    assert len(real) == 2 and len(fixtures) == 1
    assert len(real) + len(fixtures) == len(rows)


# -- the enum is an allowlist, not a denylist --------------------------------
#
# These iterate every member rather than naming one. That is the whole point:
# the previous predicates were phrased as "is not PRODUCTION_READONLY", so
# adding a mode silently granted it write access and no test noticed. Any
# fifth mode now has to be a deliberate edit here.

def test_only_named_modes_allow_writes():
    allowed = {m for m in cfg.DeploymentMode if m.writes_allowed}
    assert allowed == {
        cfg.DeploymentMode.SANDBOX,
        cfg.DeploymentMode.PRODUCTION_WRITE,
    }


def test_every_non_sandbox_mode_is_flagged_production():
    production = {m for m in cfg.DeploymentMode if m.is_production}
    assert production == set(cfg.DeploymentMode) - {cfg.DeploymentMode.SANDBOX}


def test_only_the_files_mode_adds_downloads_without_writes():
    downloaders = {m for m in cfg.DeploymentMode if m.download_requests_allowed}
    assert downloaders == {
        cfg.DeploymentMode.SANDBOX,
        cfg.DeploymentMode.PRODUCTION_READONLY_FILES,
        cfg.DeploymentMode.PRODUCTION_WRITE,
    }
    # The distinguishing property: it downloads but cannot write.
    files = cfg.DeploymentMode.PRODUCTION_READONLY_FILES
    assert files.download_requests_allowed and not files.writes_allowed


def test_strict_readonly_grants_nothing():
    strict = cfg.DeploymentMode.PRODUCTION_READONLY
    assert not strict.writes_allowed
    assert not strict.download_requests_allowed


def test_mode_labels_are_distinct():
    """Each mode must be distinguishable in buildium_health output.

    'production-readonly' is a prefix of 'production-readonly-files', so any
    code or test that substring-matches a mode silently stops discriminating.
    """
    labels = [_conf(Path("/tmp"), m).environment for m in cfg.DeploymentMode]
    assert len(set(labels)) == len(labels)


# -- the download carve-out ---------------------------------------------------

def test_download_allowlist_matches_the_spec_exactly(index):
    """Re-derive the seven paths from the spec rather than trusting the literal.

    This is what makes the singular/plural split safe permanently: a spec
    update that adds an eighth download endpoint fails here instead of
    quietly leaving that file type undownloadable.
    """
    derived = {
        ep.path
        for ep in index.endpoints
        if ep.method.lower() == "post"
        and ep.path.rstrip("/").split("/")[-1].lower()
        in ("downloadrequest", "downloadrequests")
    }
    assert derived == set(cfg.DOWNLOAD_REQUEST_PATHS)
    assert len(derived) == 7


def test_files_mode_exempts_exactly_seven_operations(index):
    """Exhaustive scope proof over every POST in the spec.

    The old guarantee was 'writes are impossible'. This is its replacement:
    not 'these examples are blocked' but 'of ~120 POST operations, precisely
    these seven are reachable and no others'.
    """
    files = cfg.DeploymentMode.PRODUCTION_READONLY_FILES
    permitted, refused = set(), set()
    for ep in index.endpoints:
        if ep.method.lower() != "post":
            continue
        concrete = re.sub(r"\{[^}]+\}", "1", ep.path)
        (permitted if cfg.request_permitted(files, "POST", concrete) else refused).add(ep.path)

    assert permitted == set(cfg.DOWNLOAD_REQUEST_PATHS)
    assert len(refused) > 100, "sanity: the spec should have many other POSTs"


@pytest.mark.parametrize("path,allowed", [
    ("/v1/files/5/downloadrequest", True),
    ("/v1/bills/7/files/5/downloadrequest", True),
    ("/v1/rentals/13641/images/9/downloadrequests", True),
    ("/v1/rentals/units/4/images/9/downloadrequests", True),
    ("/v1/bankaccounts/1/checks/2/files/3/downloadrequests", True),
    ("/v1/FILES/5/DownloadRequest", True),          # Buildium routes case-insensitively
    ("/v1/files/5/downloadrequest\n", False),       # \Z, not $
    ("/v1/files/5/downloadrequest/", False),        # trailing slash
    ("/v1/files/5/downloadrequest/../../leases", False),
    ("/v1/files/5/downloadrequest%2f..%2fleases", False),
    ("/v1/files/%2e%2e/leases/5/downloadrequest", False),
    ("/v1/files/5/downloadrequest;/v1/leases", False),
    ("/v1/files/5/downloadrequest%00", False),
    ("/v1/files/abc/downloadrequest", False),       # non-numeric id
    ("/v1/files//downloadrequest", False),          # empty id
    ("/v1/files/99999999999999/downloadrequest", False),  # overlong id
    ("/v1/leases/5/downloadrequest", False),        # not a real endpoint
    ("", False),
])
def test_download_allowlist_unit_cases(path, allowed):
    assert cfg.is_download_request_path(path) is allowed


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_files_mode_refuses_non_post_on_a_download_path(method):
    assert not cfg.request_permitted(
        cfg.DeploymentMode.PRODUCTION_READONLY_FILES,
        method,
        "/v1/files/5/downloadrequest",
    )


def test_strict_readonly_still_refuses_downloadrequest():
    """The two read-only modes must stay distinguishable."""
    assert not cfg.request_permitted(
        cfg.DeploymentMode.PRODUCTION_READONLY, "POST", "/v1/files/5/downloadrequest"
    )
    assert cfg.request_permitted(
        cfg.DeploymentMode.PRODUCTION_READONLY_FILES, "POST", "/v1/files/5/downloadrequest"
    )


def test_reads_are_permitted_in_every_mode():
    for m in cfg.DeploymentMode:
        assert cfg.request_permitted(m, "GET", "/v1/leases")


# -- the guard at the transport layer, with httpx's own normalization ---------
#
# These build requests through httpx rather than passing strings, so whatever
# httpx does to a path before it reaches the guard is part of what is tested.

class _StubTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.sent = []

    async def handle_async_request(self, request):
        self.sent.append(request)
        return httpx.Response(200, json={})


def _guard(mode):
    inner = _StubTransport()
    guard = client_mod.ReadOnlyTransportGuard(
        inner,
        mode=mode,
        allowed_hosts=cfg.SANDBOX_HOSTS | cfg.PRODUCTION_HOSTS,
    )
    return guard, inner


async def _send(guard, method, url, base="https://api.buildium.com"):
    """Build through httpx so its own URL normalization is part of the test."""
    with httpx.Client(base_url=base) as c:
        request = c.build_request(method, url)
    return await guard.handle_async_request(request)


@pytest.mark.parametrize("url,allowed", [
    ("/v1/files/5/downloadrequest", True),
    ("/v1/files/5/downloadrequest?x=1", True),          # query stripped
    ("/v1/rentals/13641/images/9/downloadrequests", True),
    # httpx collapses this to the real endpoint before the guard sees it.
    ("/v1/leases/../files/5/downloadrequest", True),
    ("/v1/files/5/downloadrequest/../../leases", False),
    ("/v1/files/5/downloadrequest%2f..%2fleases", False),
    ("/v1/files/%2e%2e/leases/5/downloadrequest", False),
    ("/v1/files/5/downloadrequest;/v1/leases", False),
    ("/v1/files/abc/downloadrequest", False),
    ("/v1/leases/5/downloadrequest", False),
    ("/v1/vendors", False),
])
async def test_download_allowlist_through_the_transport(url, allowed):
    guard, inner = _guard(cfg.DeploymentMode.PRODUCTION_READONLY_FILES)
    if allowed:
        await _send(guard, "POST", url)
        assert len(inner.sent) == 1
    else:
        with pytest.raises(client_mod.ReadOnlyViolation):
            await _send(guard, "POST", url)
        assert inner.sent == []


async def test_guard_refuses_a_download_path_on_a_foreign_host():
    """An absolute URL retargets the host; the path allowlist alone is not enough."""
    guard, inner = _guard(cfg.DeploymentMode.PRODUCTION_READONLY_FILES)
    with pytest.raises(client_mod.ReadOnlyViolation, match="not an approved"):
        await _send(guard, "POST", "https://evil.example.com/v1/files/5/downloadrequest")
    assert inner.sent == []


async def test_strict_readonly_refuses_downloads_at_the_transport():
    guard, inner = _guard(cfg.DeploymentMode.PRODUCTION_READONLY)
    with pytest.raises(client_mod.ReadOnlyViolation):
        await _send(guard, "POST", "/v1/files/5/downloadrequest")
    assert inner.sent == []


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
async def test_files_mode_refuses_other_methods_at_the_transport(method):
    guard, inner = _guard(cfg.DeploymentMode.PRODUCTION_READONLY_FILES)
    with pytest.raises(client_mod.ReadOnlyViolation):
        await _send(guard, method, "/v1/files/5/downloadrequest")
    assert inner.sent == []


async def test_reads_pass_the_guard_in_every_readonly_mode():
    for mode in (cfg.DeploymentMode.PRODUCTION_READONLY,
                 cfg.DeploymentMode.PRODUCTION_READONLY_FILES):
        guard, inner = _guard(mode)
        await _send(guard, "GET", "/v1/leases")
        assert len(inner.sent) == 1


def test_check_write_permits_a_download_request_in_files_mode(tmp_path, monkeypatch):
    """Covers the early return: fixtures mode must not then demand a name prefix."""
    monkeypatch.setenv("BUILDIUM_WRITE_MODE", "fixtures")
    conf = _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_READONLY_FILES,
                 base_url="https://api.buildium.com")
    check_write("POST", "/v1/files/5/downloadrequest", {}, FixtureTracker(conf))

    with pytest.raises(GuardViolation):
        check_write("POST", "/v1/vendors", {"Name": "ZZ-MCPTEST-x"},
                    FixtureTracker(conf))


# -- packaging and deferred startup ------------------------------------------

def test_spec_ships_inside_the_package():
    """A wheel must carry the spec, or a pip install cannot start at all."""
    packaged = paths.packaged_spec_path()
    assert packaged.is_file()
    assert packaged.parent.name == "specs"
    assert packaged.parent.parent.name == "buildium_mcp"


def test_no_path_escapes_the_package():
    """Guard against PROJECT_ROOT coming back.

    `Path(__file__).parents[2]` is correct in a checkout and points inside the
    interpreter's lib directory in a wheel. Every use of it was a bug.
    """
    import ast

    for module in ("config.py", "paths.py", "runtime.py"):
        tree = ast.parse((ROOT / "src" / "buildium_mcp" / module).read_text())
        # Fixed-depth indexing is the bug: parents[2] is the repo root in a
        # checkout and the interpreter's lib directory in a wheel. Iterating
        # parents to find a marker file is fine — it cannot be wrong that way.
        offenders = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "parents"
        ]
        assert not offenders, (
            f"{module} indexes __file__.parents by depth; that is correct in a "
            "checkout and wrong in a wheel. Search upward for a marker instead."
        )


def test_log_paths_land_under_the_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDIUM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("BUILDIUM_RUN_LOG", raising=False)
    monkeypatch.delenv("BUILDIUM_ARTIFACT_LOG", raising=False)
    run_log, artifact_log, error = paths.resolve_log_paths()
    assert error is None
    assert run_log is not None and artifact_log is not None
    for path in (run_log, artifact_log):
        assert str(path).startswith(str(tmp_path))
        assert "site-packages" not in str(path)


def test_unwritable_state_dir_disables_logging_visibly(tmp_path, monkeypatch):
    """Degrade, but never silently — the old code swallowed OSError at the
    write site, so a broken audit trail was indistinguishable from a working
    one while the README promised every request was logged."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setenv("BUILDIUM_STATE_DIR", str(locked / "state"))
    try:
        run_log, artifact_log, error = paths.resolve_log_paths()
        assert run_log is None and artifact_log is None
        assert error and str(locked) in error
    finally:
        locked.chmod(0o700)


def test_logging_can_be_turned_off_explicitly(monkeypatch):
    monkeypatch.setenv("BUILDIUM_RUN_LOG", "off")
    monkeypatch.setenv("BUILDIUM_ARTIFACT_LOG", "off")
    run_log, artifact_log, error = paths.resolve_log_paths()
    assert run_log is None and artifact_log is None
    assert error and "disabled" in error


def test_importing_the_server_needs_no_credentials():
    """The whole point of deferred startup: import must not touch config."""
    import importlib

    from buildium_mcp import server as server_mod

    importlib.reload(server_mod)  # must not raise


def test_local_tools_work_without_credentials():
    """A misconfigured server should still be able to explain the API."""
    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod

    rt_mod.reset()
    try:
        assert server_mod.list_tags()["ok"] is True
        assert server_mod.search_endpoints("lease", limit=1)["ok"] is True
    finally:
        rt_mod.reset()


def test_a_broken_config_returns_data_not_a_traceback():
    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod

    rt_mod.reset()
    try:
        result = asyncio.run(server_mod.list_rentals())
        assert result["ok"] is False
        assert result["type"] == "StartupError"
        assert result["remedy"], "an error without a fix is not much of an error"

        health = server_mod.health()
        assert health["ok"] is False
        assert health["stage"] == "credentials"
        assert health["checks"]["spec"].startswith("ok")
    finally:
        rt_mod.reset()


def test_health_never_raises_even_on_a_bad_mode(monkeypatch):
    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod

    monkeypatch.setenv(cfg.MODE_ENV_VAR, "not-a-mode")
    rt_mod.reset()
    try:
        health = server_mod.health()
        assert health["ok"] is False
        assert health["stage"] == "mode"
        assert health["deployment_mode"] == "sandbox", "must fall back to the safe mode"
    finally:
        rt_mod.reset()


# -- the banner ---------------------------------------------------------------

def _status(**overrides):
    from buildium_mcp.runtime import StartupStatus

    base = dict(
        mode=cfg.DeploymentMode.SANDBOX, mode_source="default", ok=True,
        stage=None, error=None, remedy=None, checks={}, base_url="https://x",
        spec_path="/spec.json", operations=462, run_log="/run.log",
        log_dir_error=None, env_files_loaded=(), write_mode="fixtures",
        writes_allowed=True, download_requests_allowed=True,
    )
    base.update(overrides)
    return StartupStatus(**base)


def test_banner_names_the_mode_and_its_source():
    from buildium_mcp.banner import render_banner

    text = render_banner(_status(mode_source=cfg.MODE_ENV_VAR))
    assert "sandbox" in text
    assert cfg.MODE_ENV_VAR in text, "'I never set that' must be distinguishable"


def test_banner_shouts_about_production_writes():
    from buildium_mcp.banner import render_banner

    text = render_banner(_status(mode=cfg.DeploymentMode.PRODUCTION_WRITE))
    assert "!!!" in text and "LIVE PRODUCTION RECORDS" in text


def test_banner_distinguishes_the_two_readonly_modes():
    from buildium_mcp.banner import render_banner

    strict = render_banner(_status(mode=cfg.DeploymentMode.PRODUCTION_READONLY,
                                   writes_allowed=False,
                                   download_requests_allowed=False))
    files = render_banner(_status(mode=cfg.DeploymentMode.PRODUCTION_READONLY_FILES,
                                  writes_allowed=False,
                                  download_requests_allowed=True))
    assert strict != files
    assert "blocked" in strict and "permitted" in files


def test_banner_and_health_never_contain_a_secret(monkeypatch):
    """Feed a real secret through the real path and assert it never comes out.

    The earlier version of this test rendered a StartupStatus that had no
    credential in it and asserted "SUPERSECRET" was absent — which it was,
    trivially. Here the secret goes in through the environment, load_config
    reads it, and both the banner and buildium_health's payload are checked.
    """
    import json as _json

    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod
    from buildium_mcp.banner import render_banner

    secret = "SUPERSECRET-9f3a7c1e-do-not-print"
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "client-id-SUPERSECRET-too")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", secret)
    rt_mod.reset()
    try:
        status = rt_mod.startup_status()
        assert status.ok, status.error
        assert rt_mod.get_runtime().config.client_secret == secret  # it really went in
        text = render_banner(status)
        health = _json.dumps(server_mod.health(), default=str)
        for out in (text, health):
            assert secret not in out
            assert "SUPERSECRET" not in out
            for word in ("client_secret", "CLIENT_SECRET", "x-buildium-client-secret"):
                assert word not in out
    finally:
        rt_mod.reset()


async def test_audit_log_never_contains_a_secret(tmp_path, monkeypatch):
    """The request goes out with credential headers; the audit line must not."""
    import json as _json

    secret = "SUPERSECRET-audit-3b2c"
    conf = cfg.Config(
        base_url="https://apisandbox.buildium.com", client_id="id-SUPERSECRET",
        client_secret=secret, spec_path=SPEC, run_log=tmp_path / "run.log",
        artifact_log=None, fixture_prefix="ZZ-MCPTEST-",
    )
    client = BuildiumClient(conf)
    inner = _StubTransport()
    client._client._transport = inner
    try:
        await client.request("GET", "/v1/leases", query={"limit": 1})
    finally:
        await client.aclose()
    assert inner.sent[0].headers["x-buildium-client-secret"] == secret  # it was sent
    lines = (tmp_path / "run.log").read_text().splitlines()
    assert len(lines) == 1
    record = _json.loads(lines[0])
    assert record["method"] == "GET" and record["path"] == "/v1/leases"
    assert "SUPERSECRET" not in lines[0]


def test_guarded_decorator_does_not_alter_any_tool_schema():
    """_guarded must be invisible to FastMCP.

    FastMCP derives each tool's schema by inspecting the callable. The wrapper
    is signature-transparent only because of functools.wraps: drop it and every
    tool collapses to (*args, **kwargs), which FastMCP rejects outright. That
    is what this test actually catches, and it is the failure that would
    otherwise turn a refactor of _guarded into nineteen broken tools.

    Note it does NOT catch a parameter added to the wrapper itself —
    inspect.signature follows __wrapped__ back to the original — so the leak
    assertions below are belt-and-braces rather than the primary guarantee.
    """
    from buildium_mcp import server as server_mod

    tools = asyncio.run(server_mod.mcp.list_tools())
    assert len(tools) == 19, f"expected 19 tools, found {len(tools)}"

    for tool in tools:
        schema = tool.parameters
        props = schema.get("properties", {})
        for leaked in ("rt", "runtime", "args", "kwargs", "self"):
            assert leaked not in props, f"{tool.name} leaks {leaked!r} into its schema"
        assert tool.description, f"{tool.name} lost its docstring"


def test_every_tool_is_annotated():
    """Annotations tell a client what is safe to retry or auto-approve."""
    from buildium_mcp import server as server_mod

    tools = asyncio.run(server_mod.mcp.list_tools())
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.read_only_hint is not None, tool.name


def test_no_tool_references_a_module_global_that_no_longer_exists():
    """Catch the class of bug that deferred startup introduces.

    Moving config/client/index/tracker off the module means every tool body has
    to rebind them. A missed one is invisible until that exact code path runs —
    and the two that were missed first time were on write paths, which the
    offline suite does not exercise. So scan the AST instead of relying on
    coverage.
    """
    import ast

    stale = {"config", "client", "tracker", "index"}
    tree = ast.parse((ROOT / "src" / "buildium_mcp" / "server.py").read_text())

    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {
            t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)
        } | {a.arg for a in fn.args.args}
        offenders += [
            f"{fn.name}() uses bare {n.id!r} at line {n.lineno}"
            for n in ast.walk(fn)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            and n.id in stale and n.id not in bound
        ]

    assert offenders == [], "\n".join(offenders)


# -- the guard judges methods by allowlist ------------------------------------
#
# The first version refused POST/PUT/PATCH/DELETE and let everything else
# through, on the theory that nothing else writes. That makes the guard depend
# on what Buildium's server does with TRACE, PROPFIND or a mistyped "P0ST" —
# which is not structural. Now only GET, HEAD and OPTIONS leave the process.


@pytest.mark.parametrize("method", ["TRACE", "PROPFIND", "MERGE", "PURGE", "P0ST",
                                    "POST ", " delete", "DELETE\n", "GETS"])
async def test_readonly_guard_refuses_unknown_and_malformed_methods(method):
    for mode in (cfg.DeploymentMode.PRODUCTION_READONLY,
                 cfg.DeploymentMode.PRODUCTION_READONLY_FILES):
        guard, inner = _guard(mode)
        request = httpx.Request(method, "https://api.buildium.com/v1/vendors/1")
        with pytest.raises(client_mod.ReadOnlyViolation):
            await guard.handle_async_request(request)
        assert inner.sent == []


def test_safe_methods_are_exactly_get_head_options():
    assert cfg.SAFE_METHODS == {"GET", "HEAD", "OPTIONS"}
    for mode in cfg.DeploymentMode:
        for method in cfg.SAFE_METHODS:
            assert cfg.request_permitted(mode, method, "/v1/leases")
        assert not cfg.request_permitted(
            cfg.DeploymentMode.PRODUCTION_READONLY, "PROPFIND", "/v1/leases"
        )


async def test_guard_binds_host_and_scheme_for_reads_too():
    """A GET carries the credential headers, so a retargeted GET is a leak.

    The first version only checked the host for mutating methods.
    """
    guard, inner = _guard(cfg.DeploymentMode.PRODUCTION_READONLY)
    for url in ("https://evil.example.com/v1/leases",
                "http://api.buildium.com/v1/leases",           # cleartext
                "https://api.buildium.com.evil.example/v1/leases",
                "https://api.buildium.com@evil.example/v1/leases"):
        with pytest.raises(client_mod.ReadOnlyViolation, match="not an approved"):
            await guard.handle_async_request(httpx.Request("GET", url))
    assert inner.sent == []
    await guard.handle_async_request(
        httpx.Request("GET", "https://API.buildium.com/v1/leases")
    )
    assert len(inner.sent) == 1


# -- the file helpers are confined to their endpoints in every mode -----------
#
# buildium_download_file and buildium_upload_file take their request path from
# the caller. Before this, in sandbox or production-write mode, that made the
# "download" tool — annotated read-only — an arbitrary empty-body POST, and the
# "upload" tool an arbitrary POST with a metadata body, neither of which went
# through the spec lookup or the fixture tracker that call_endpoint applies.


def test_upload_allowlist_matches_the_spec_exactly(index):
    derived = {
        ep.path for ep in index.endpoints
        if ep.method.lower() == "post" and ep.path.rstrip("/").endswith("/uploads")
    }
    assert derived == set(cfg.UPLOAD_REQUEST_PATHS)
    assert len(derived) == 7


@pytest.mark.parametrize("path,allowed", [
    ("/v1/files/uploads", True),
    ("/v1/bills/12/files/uploads", True),
    ("/v1/rentals/units/4/images/uploads", True),
    ("/v1/files/uploads/", False),
    ("/v1/files/uploads/../../vendors", False),
    ("/v1/vendors", False),
    ("/v1/files/5/downloadrequest", False),      # a download path is not an upload path
    ("", False),
])
def test_upload_allowlist_unit_cases(path, allowed):
    assert cfg.is_upload_request_path(path) is allowed


def test_no_read_only_mode_permits_an_upload_request():
    """Uploads are writes. The allowlist confines the helper; it grants nothing."""
    for mode in (cfg.DeploymentMode.PRODUCTION_READONLY,
                 cfg.DeploymentMode.PRODUCTION_READONLY_FILES):
        for template in cfg.UPLOAD_REQUEST_PATHS:
            concrete = re.sub(r"\{[^}]+\}", "1", template)
            assert not cfg.request_permitted(mode, "POST", concrete)


def _client_with_stub(tmp_path, mode):
    """A BuildiumClient whose network is a stub, guard preserved if installed."""
    client = BuildiumClient(_conf(tmp_path, mode))
    stub = _StubTransport()
    transport = client._client._transport
    if isinstance(transport, ReadOnlyTransportGuard):
        transport._inner = stub
    else:
        client._client._transport = stub
    return client, stub


@pytest.mark.parametrize("mode", list(cfg.DeploymentMode))
async def test_download_helper_refuses_a_non_download_path_in_every_mode(tmp_path, mode):
    client, stub = _client_with_stub(tmp_path, mode)
    try:
        for path in ("/v1/vendors", "v1/vendors", "/v1/files/5/downloadrequest/../../vendors"):
            with pytest.raises(client_mod.BuildiumError, match="not a Buildium download"):
                await client.download_file(path)
        assert stub.sent == [], "nothing may reach the network"
    finally:
        await client.aclose()


async def test_download_helper_posts_only_to_the_download_endpoint(tmp_path):
    """Positive control for the test above: a real download path does go out."""
    client, stub = _client_with_stub(tmp_path, cfg.DeploymentMode.SANDBOX)
    try:
        # The stub answers {} — no DownloadUrl — so the helper stops after the
        # ticket request and never opens the unguarded transfer client.
        with pytest.raises(client_mod.BuildiumError, match="no DownloadUrl"):
            await client.download_file("v1/files/5/downloadrequest")
        assert [(r.method, r.url.path) for r in stub.sent] == [
            ("POST", "/v1/files/5/downloadrequest")
        ]
    finally:
        await client.aclose()


@pytest.mark.parametrize("mode", list(cfg.DeploymentMode))
async def test_upload_helper_refuses_a_non_upload_path_in_every_mode(tmp_path, mode):
    client, stub = _client_with_stub(tmp_path, mode)
    try:
        for path in ("/v1/vendors", "/v1/files/5/downloadrequest", "/v1/files/uploads/x"):
            with pytest.raises(client_mod.BuildiumError, match="not a Buildium upload"):
                await client.upload_file(path, {"Title": "ZZ-MCPTEST-x"}, b"x", "x.txt")
        assert stub.sent == []
    finally:
        await client.aclose()


async def test_upload_helper_posts_only_to_the_upload_endpoint(tmp_path):
    client, stub = _client_with_stub(tmp_path, cfg.DeploymentMode.SANDBOX)
    try:
        with pytest.raises(client_mod.BuildiumError, match="no UploadUrl"):
            await client.upload_file("/v1/files/uploads", {"Title": "ZZ-MCPTEST-x"}, b"x", "x.txt")
        assert [(r.method, r.url.path) for r in stub.sent] == [("POST", "/v1/files/uploads")]
    finally:
        await client.aclose()


async def test_file_tools_refuse_a_foreign_path_before_any_request(tmp_path, monkeypatch):
    """Through the MCP tool functions themselves, with a live runtime."""
    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod

    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    monkeypatch.setenv("BUILDIUM_STATE_DIR", str(tmp_path / "state"))
    rt_mod.reset()
    try:
        rt = rt_mod.get_runtime()
        assert rt.config.mode is cfg.DeploymentMode.SANDBOX  # the unguarded mode
        stub = _StubTransport()
        rt.client._client._transport = stub

        result = await server_mod.download_file(
            5, str(tmp_path / "out.bin"), download_path="/v1/vendors"
        )
        assert result["ok"] is False and "download-request" in result["error"]

        source = tmp_path / "ZZ-MCPTEST-x.txt"
        source.write_bytes(b"x")
        result = await server_mod.upload_file(
            str(source), "ZZ-MCPTEST-x", 1, upload_path="/v1/vendors"
        )
        assert result["ok"] is False and "upload-request" in result["error"]
        assert stub.sent == []
    finally:
        rt_mod.reset()


# -- .env files supply only this server's settings -----------------------------

# conftest replaces env_file_candidates for every test; keep the real one.
_REAL_ENV_FILE_CANDIDATES = paths.env_file_candidates


def test_env_file_supplies_only_buildium_settings(tmp_path):
    """HTTPS_PROXY plus SSL_CERT_FILE in a stray .env was enough to route the
    credentialed client through a proxy that could read the secret."""
    env = tmp_path / ".env"
    env.write_text(
        "BUILDIUM_CLIENT_ID=from-file\n"
        "HTTPS_PROXY=http://127.0.0.1:9\n"
        "SSL_CERT_FILE=./ca.pem\n"
        "PATH=/nowhere\n"
    )
    environ: dict[str, str] = {}
    cfg.import_env_file(env, environ)
    assert environ == {"BUILDIUM_CLIENT_ID": "from-file"}


def test_env_file_never_overrides_what_is_already_set(tmp_path):
    env = tmp_path / ".env"
    env.write_text("BUILDIUM_CLIENT_ID=from-file\nBUILDIUM_CLIENT_SECRET=s\n")
    environ = {"BUILDIUM_CLIENT_ID": "from-client"}
    cfg.import_env_file(env, environ)
    assert environ == {"BUILDIUM_CLIENT_ID": "from-client",
                       "BUILDIUM_CLIENT_SECRET": "s"}


def test_load_config_reads_credentials_from_an_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("BUILDIUM_CLIENT_ID=file-id\nBUILDIUM_CLIENT_SECRET=file-secret\n"
                   "HTTPS_PROXY=http://127.0.0.1:9\n")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    # Registered with monkeypatch so the values load_config sets are undone.
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "")
    monkeypatch.delenv("BUILDIUM_CLIENT_ID")
    monkeypatch.delenv("BUILDIUM_CLIENT_SECRET")
    monkeypatch.setattr(paths, "env_file_candidates", lambda: [env])

    conf = cfg.load_config()
    assert (conf.client_id, conf.client_secret) == ("file-id", "file-secret")
    assert conf.env_files_loaded == (str(env),)
    import os
    assert "HTTPS_PROXY" not in os.environ


def test_the_working_directory_env_is_not_read(tmp_path, monkeypatch):
    """An MCP client starts the server wherever it likes; Claude Code uses the
    open project. That project's .env is not this server's configuration."""
    project = tmp_path / "someone-elses-project"
    project.mkdir()
    (project / ".env").write_text("BUILDIUM_WRITE_MODE=open\n")
    monkeypatch.chdir(project)
    monkeypatch.setenv("BUILDIUM_CONFIG_DIR", str(tmp_path / "config"))

    candidates = _REAL_ENV_FILE_CANDIDATES()
    assert project / ".env" not in candidates
    assert candidates[-1] == tmp_path / "config" / ".env"


def test_checkout_root_finds_this_checkout():
    assert paths.checkout_root() == ROOT


def test_checkout_root_ignores_a_project_that_merely_holds_the_install(tmp_path, monkeypatch):
    """pip install into ~/project/.venv put a pyproject.toml and a src/ above
    the package, and the old upward search took that for our checkout."""
    project = tmp_path / "other-project"
    (project / "src").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'other'\n")
    installed = project / ".venv/lib/python3.11/site-packages/buildium_mcp/paths.py"
    installed.parent.mkdir(parents=True)
    installed.touch()
    monkeypatch.setattr(paths, "__file__", str(installed))
    assert paths.checkout_root() is None


def test_checkout_root_recognizes_a_checkout_by_the_package_position(tmp_path, monkeypatch):
    module = tmp_path / "checkout" / "src" / "buildium_mcp" / "paths.py"
    module.parent.mkdir(parents=True)
    module.touch()
    (tmp_path / "checkout" / "pyproject.toml").write_text("[project]\n")
    monkeypatch.setattr(paths, "__file__", str(module))
    assert paths.checkout_root() == (tmp_path / "checkout").resolve()


# -- a blank fixture prefix is not a prefix --------------------------------------


@pytest.mark.parametrize("raw", ["", "   "])
def test_a_blank_fixture_prefix_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    monkeypatch.setenv("BUILDIUM_FIXTURE_PREFIX", raw)
    assert cfg.load_config().fixture_prefix == cfg.DEFAULT_FIXTURE_PREFIX


def test_a_custom_fixture_prefix_is_kept(monkeypatch):
    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    monkeypatch.setenv("BUILDIUM_FIXTURE_PREFIX", "QA-")
    assert cfg.load_config().fixture_prefix == "QA-"


@pytest.mark.parametrize("base_url", ["https://apisandbox.buildium.com",
                                      "https://api.buildium.com"])
def test_the_guard_refuses_every_create_under_a_blank_prefix(tmp_path, base_url):
    """Every string starts with "", so a blank prefix passed a real name
    against production in fixtures mode."""
    import dataclasses

    conf = dataclasses.replace(
        _conf(tmp_path, cfg.DeploymentMode.PRODUCTION_WRITE, base_url=base_url),
        fixture_prefix="",
    )
    with pytest.raises(GuardViolation, match="prefix is empty"):
        check_write("POST", "/v1/rentals/owners", {"FirstName": "Real"},
                    FixtureTracker(conf))


# -- lease_roster reads every page ------------------------------------------------


class _TenantTransport(httpx.AsyncBaseTransport):
    """`total` tenants, two to a lease, one lease to a unit: tenant i is on
    lease 1000 + i // 2, which is on unit 5000 + i // 2. Honours `unitids`."""

    def __init__(self, total: int, lease_has_unit: bool = True):
        self.tenants = [
            {"Id": i, "FirstName": f"T{i}", "LastName": "X", "Email": f"t{i}@x",
             "Leases": [{"Id": 1000 + i // 2, "UnitId": 5000 + i // 2}]}
            for i in range(total)
        ]
        self.lease_has_unit = lease_has_unit
        self.requests: list[tuple[str, dict[str, str]]] = []

    async def handle_async_request(self, request):
        params = dict(request.url.params)
        self.requests.append((request.url.path, params))
        if request.url.path.startswith("/v1/leases/") and request.url.path[11:].isdigit():
            lease_id = int(request.url.path[11:])
            if not 1000 <= lease_id < 1000 + (len(self.tenants) + 1) // 2:
                return httpx.Response(404, json={"UserMessage": "Lease not found"})
            lease = {"Id": lease_id}
            if self.lease_has_unit:
                lease["UnitId"] = 5000 + (lease_id - 1000)
            return httpx.Response(200, json=lease)
        assert request.url.path == "/v1/leases/tenants"
        rows = self.tenants
        if "unitids" in params:
            unit = int(params["unitids"])
            rows = [t for t in rows if t["Leases"][0]["UnitId"] == unit]
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))
        return httpx.Response(200, json=rows[offset:offset + limit])

    def tenant_pages(self):
        return [p for path, p in self.requests if path == "/v1/leases/tenants"]

    async def aclose(self):
        return None


@pytest.fixture
def roster_runtime(monkeypatch):
    from buildium_mcp import runtime as rt_mod

    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    rt_mod.reset()

    def install(total, **kwargs):
        transport = _TenantTransport(total, **kwargs)
        rt_mod.get_runtime().client._client._transport = transport
        return transport

    yield install
    rt_mod.reset()


async def test_roster_follows_every_page(roster_runtime):
    from buildium_mcp import server as server_mod

    transport = roster_runtime(250)
    result = await server_mod.lease_roster(limit=100)
    assert result["tenants_seen"] == 250
    assert result["lease_count"] == 125
    assert result["multi_tenant_lease_count"] == 125
    assert result["complete"] is True and result["truncated_at"] is None
    assert len(transport.tenant_pages()) == 3


async def test_roster_reads_well_past_a_thousand_tenants(roster_runtime):
    """The first fix reused the list tools' 1000-record ceiling, which is a
    context limit. The roster returns a compact join, so it does not apply."""
    from buildium_mcp import server as server_mod

    transport = roster_runtime(4500)
    result = await server_mod.lease_roster()
    assert result["complete"] is True
    assert result["tenants_seen"] == 4500
    assert result["lease_count"] == 2250
    assert [p["limit"] for p in transport.tenant_pages()] == ["1000"] * 5


async def test_roster_for_one_lease_reads_only_its_unit(roster_runtime):
    """A lease past the first page came back empty; and scanning the whole
    portfolio to answer for one lease cost a request per thousand tenants."""
    from buildium_mcp import server as server_mod

    transport = roster_runtime(5000)
    result = await server_mod.lease_roster(lease_id=2100)
    assert result["lease_count"] == 1
    assert [t["TenantId"] for t in result["roster"][0]["Tenants"]] == [2200, 2201]
    assert [path for path, _ in transport.requests] == [
        "/v1/leases/2100", "/v1/leases/tenants",
    ]
    assert transport.tenant_pages()[0]["unitids"] == "6100"


async def test_roster_for_one_lease_falls_back_to_a_scan_without_a_unit(roster_runtime):
    from buildium_mcp import server as server_mod

    transport = roster_runtime(250, lease_has_unit=False)
    result = await server_mod.lease_roster(lease_id=1100)
    assert result["lease_count"] == 1
    assert "unitids" not in transport.tenant_pages()[0]


async def test_roster_for_a_missing_lease_is_an_error(roster_runtime):
    from buildium_mcp import server as server_mod

    roster_runtime(10)
    result = await server_mod.lease_roster(lease_id=999999)
    assert result["ok"] is False and result["status"] == 404


async def test_roster_passes_lease_status_through(roster_runtime):
    from buildium_mcp import server as server_mod

    transport = roster_runtime(10)
    await server_mod.lease_roster(lease_status="Active", property_id=7)
    page = transport.tenant_pages()[0]
    assert page["leasetermstatuses"] == "Active" and page["propertyids"] == "7"


async def test_roster_omits_per_lease_detail_for_a_large_portfolio(roster_runtime, monkeypatch):
    """Hundreds of leases, tenant by tenant, is more than a client accepts as
    one result. The counts are what a whole-portfolio question needs."""
    from buildium_mcp import server as server_mod

    monkeypatch.setattr(server_mod, "ROSTER_DETAIL_MAX_LEASES", 10)
    roster_runtime(250)
    result = await server_mod.lease_roster()
    assert result["roster_omitted"] is True
    assert "roster" not in result and "multi_tenant_leases" not in result
    assert result["lease_count"] == 125 and result["multi_tenant_lease_count"] == 125
    assert "property_id" in result["roster_note"]


async def test_roster_counts_genuine_co_tenancies_even_without_detail(roster_runtime, monkeypatch):
    from buildium_mcp import server as server_mod

    monkeypatch.setattr(server_mod, "ROSTER_DETAIL_MAX_LEASES", 10)
    transport = roster_runtime(250)
    transport.tenants[0]["FirstName"] = "ZZ-MCPTEST-T0"   # lease 1000 is now fixture-made
    result = await server_mod.lease_roster()
    assert result["multi_tenant_lease_count"] == 125
    assert result["multi_tenant_lease_count_excluding_fixtures"] == 124
    assert "multi_tenant_leases_excluding_fixtures" not in result


async def test_roster_says_so_when_it_stops_short(roster_runtime, monkeypatch):
    from buildium_mcp import server as server_mod

    monkeypatch.setattr(server_mod, "ROSTER_MAX_TENANTS", 100)
    roster_runtime(250)
    result = await server_mod.lease_roster()
    assert result["complete"] is False and result["truncated_at"] == 100
    assert "property_id" in result["truncation_note"]


async def test_roster_limit_is_a_page_size_clamped_to_buildiums_maximum(roster_runtime):
    from buildium_mcp import server as server_mod

    transport = roster_runtime(10)
    await server_mod.lease_roster(limit=5000)
    assert transport.tenant_pages()[0]["limit"] == "1000"


async def test_get_all_pages_can_compact_records_as_they_arrive(tmp_path):
    client, _ = _paging_client(tmp_path, 250)
    records, truncated = await client.get_all_pages(
        "/v1/leases", page_size=100, keep=lambda r: r["Id"]
    )
    assert records == list(range(250)) and truncated is False
    await client.aclose()


# -- Retry-After ---------------------------------------------------------------------


@pytest.mark.parametrize("header, expected", [
    ("3", 3.0), ("0", 0.0), ("1.5", 1.5),
    (None, 2.0), ("", 2.0), ("soon", 2.0), ("nan", 2.0), ("inf", 2.0),
    ("-5", 0.0), ("600", 30.0),
])
def test_retry_after_seconds(header, expected):
    assert client_mod._retry_after_seconds(header) == expected


def test_retry_after_accepts_an_http_date():
    """RFC 9110 allows a date. float() raised ValueError on one, out of the
    tool call."""
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    soon = datetime.now(timezone.utc) + timedelta(seconds=10)
    assert 8 <= client_mod._retry_after_seconds(format_datetime(soon, usegmt=True)) <= 10
    assert client_mod._retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


async def test_a_429_with_a_date_retry_after_is_retried(tmp_path, monkeypatch):
    slept: list[float] = []

    async def no_wait(seconds):
        slept.append(seconds)

    monkeypatch.setattr(client_mod, "_sleep", no_wait)
    responses = [
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
        httpx.Response(200, json=[{"Id": 1}]),
    ]
    client = BuildiumClient(_conf(tmp_path, cfg.DeploymentMode.SANDBOX))
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: responses.pop(0)),
        base_url="https://apisandbox.buildium.com",
    )
    resp = await client.request("GET", "/v1/rentals")
    assert resp.status == 200 and resp.data == [{"Id": 1}]
    assert slept == [0.0]
    await client.aclose()


# -- a client that cannot be built is a startup error, not a crash -------------------


def test_a_client_that_cannot_be_built_is_reported_not_raised(tmp_path, monkeypatch):
    """httpx loads SSL_CERT_FILE when the client is built. A stale path made
    every tool, buildium_health included, raise FileNotFoundError."""
    from buildium_mcp import runtime as rt_mod
    from buildium_mcp import server as server_mod

    monkeypatch.setenv("BUILDIUM_CLIENT_ID", "x")
    monkeypatch.setenv("BUILDIUM_CLIENT_SECRET", "y")
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    rt_mod.reset()
    try:
        health = server_mod.health()
        assert health["ok"] is False
        assert health["stage"] == "client"
        assert "SSL_CERT_FILE" in health["remedy"]

        result = asyncio.run(server_mod.list_rentals())
        assert result["ok"] is False and result["type"] == "StartupError"
    finally:
        rt_mod.reset()
