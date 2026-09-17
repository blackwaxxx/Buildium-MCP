"""Configuration, deployment modes, and the host allowlist.

How much of the real world this server may touch is chosen by one environment
variable, BUILDIUM_DEPLOYMENT_MODE, defaulting to sandbox. Four states, in
increasing order of blast radius:

  sandbox                    — the only approved hosts are sandbox hosts.
                               Writes land on disposable data and are further
                               constrained by BUILDIUM_WRITE_MODE.
  production-readonly        — production hosts are reachable, but every
                               mutating method is refused at the transport
                               layer, before a socket is opened. See
                               ReadOnlyTransportGuard in client.py: structural,
                               not advisory.
  production-readonly-files  — as above, plus the seven POST endpoints Buildium
                               uses to issue file downloads. Nothing else.
  production-write           — full access to live records. Nothing here
                               protects you.

Reaching production takes two independent things: this variable *and* a
BUILDIUM_BASE_URL naming a production host. Setting the mode alone changes what
is permitted, never what is targeted.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from . import paths


class DeploymentMode(str, Enum):
    """How much of the real world this server is allowed to touch."""

    SANDBOX = "sandbox"
    PRODUCTION_READONLY = "production-readonly"
    PRODUCTION_READONLY_FILES = "production-readonly-files"
    PRODUCTION_WRITE = "production-write"

    # Both predicates below are written as allowlists on purpose. Phrased as
    # denylists — "is not PRODUCTION_READONLY" — adding a member here would
    # silently grant it write access, because every site that decides whether
    # to install a guard asks writes_allowed and nothing iterates this enum.
    # Fail closed: a new mode is powerless until it is named.

    @property
    def is_production(self) -> bool:
        return self is not DeploymentMode.SANDBOX

    @property
    def writes_allowed(self) -> bool:
        """False means writes are structurally impossible, not merely refused."""
        return self in (
            DeploymentMode.SANDBOX,
            DeploymentMode.PRODUCTION_WRITE,
        )

    @property
    def download_requests_allowed(self) -> bool:
        """May this mode POST to Buildium's file-download endpoints?

        Buildium models a file download as a POST, so a strictly read-only
        server cannot fetch a lease PDF. This carves out those seven endpoints
        and nothing else; see DOWNLOAD_REQUEST_PATHS for the scope.
        """
        return self is DeploymentMode.PRODUCTION_READONLY_FILES or self.writes_allowed


# The one environment variable that selects a deployment mode. There is
# deliberately exactly one; a test asserts that this module reads no other
# name that looks like a mode, a permission, or an escape hatch.
MODE_ENV_VAR = "BUILDIUM_DEPLOYMENT_MODE"

SANDBOX_HOSTS = frozenset({"apisandbox.buildium.com"})
PRODUCTION_HOSTS = frozenset({"api.buildium.com"})

DEFAULT_BASE_URL = "https://apisandbox.buildium.com"


# Methods that can change state. In production-readonly these never leave the
# process; see client.py.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ---------------------------------------------------------------------------
# The download carve-out.
#
# Buildium issues a file download by POSTing for a short-lived signed URL, so
# a server that refuses every POST cannot read a lease PDF. PRODUCTION_READONLY
# _FILES exempts exactly these seven operations and nothing else.
#
# Note both spellings: singular and plural. A glob on "*/downloadrequest" would
# match three and quietly leave rental images, unit images, check attachments
# and architectural-request files undownloadable. A test re-derives this set
# from the spec on every run, so a spec update cannot silently drop one.
#
# Policy (which modes may do this) lives on DeploymentMode. Scope (what "this"
# is) lives here. Keeping them apart means widening one cannot widen the other.
# ---------------------------------------------------------------------------
DOWNLOAD_REQUEST_PATHS: frozenset[str] = frozenset({
    "/v1/files/{fileId}/downloadrequest",
    "/v1/bills/{billId}/files/{fileId}/downloadrequest",
    "/v1/tasks/{taskId}/history/{taskHistoryId}/files/{fileId}/downloadrequest",
    "/v1/rentals/{propertyId}/images/{imageId}/downloadrequests",
    "/v1/rentals/units/{unitId}/images/{imageId}/downloadrequests",
    "/v1/bankaccounts/{bankAccountId}/checks/{checkId}/files/{fileId}/downloadrequests",
    "/v1/associations/ownershipaccounts/architecturalrequests"
    "/{architecturalRequestId}/files/{fileId}/downloadrequests",
})

# Every path parameter on those seven is int32 in the spec. Constraining them
# to digits is what stops a caller smuggling a separator, a dot segment or an
# encoded byte through a segment we were treating as opaque.
_ID_PATTERN = r"[0-9]{1,10}"


def _compile_allowlist(templates: frozenset[str]) -> re.Pattern[str]:
    alternatives = []
    for template in sorted(templates):
        segments = [
            _ID_PATTERN if s.startswith("{") and s.endswith("}") else re.escape(s)
            for s in template.strip("/").split("/")
        ]
        alternatives.append("/" + "/".join(segments))
    # \Z, not $: $ also matches just before a trailing newline, which is a real
    # bypass for an allowlist. re.IGNORECASE because Buildium's routing is
    # case-insensitive, so refusing /v1/Files/... would confuse without adding
    # safety — the pattern is fully anchored either way.
    return re.compile(r"\A(?:" + "|".join(alternatives) + r")\Z", re.IGNORECASE)


_DOWNLOAD_RE = _compile_allowlist(DOWNLOAD_REQUEST_PATHS)


def is_download_request_path(path: str) -> bool:
    """Is this the path of a Buildium file-download request?

    `path` must be the raw, still-percent-encoded wire path with the query
    already stripped — see client._wire_path. Passing a decoded path here would
    let %2f and %2e%2e become separators and dot segments *after* this function
    has approved the string.
    """
    return _DOWNLOAD_RE.match(path) is not None


def request_permitted(mode: DeploymentMode, method: str, path: str) -> bool:
    """The single place that decides whether a request may leave this process.

    Every enforcement point calls this — the transport guard, the client's
    pre-flight check, and the write guard — so the three cannot drift apart.
    """
    method = method.upper()
    if method not in MUTATING_METHODS:
        return True
    if mode.writes_allowed:
        return True
    # Only POST. PUT/PATCH/DELETE against a download path stay refused even
    # though the spec defines no such operations; defense in depth costs
    # nothing here.
    if method == "POST" and mode.download_requests_allowed:
        return is_download_request_path(path)
    return False


class ConfigError(RuntimeError):
    """Raised when configuration is missing, malformed, or forbidden."""


@dataclass(frozen=True)
class Config:
    base_url: str
    client_id: str
    client_secret: str
    spec_path: Path
    # None means "no audit trail is being written". Never silently: the reason
    # is carried in log_dir_error and reported by buildium_health.
    run_log: Path | None
    artifact_log: Path | None
    fixture_prefix: str
    mode: DeploymentMode = DeploymentMode.SANDBOX
    mode_source: str = "default"
    log_dir_error: str | None = None
    env_files_loaded: tuple[str, ...] = ()

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc.lower()

    @property
    def is_sandbox(self) -> bool:
        return self.host in SANDBOX_HOSTS

    @property
    def writes_allowed(self) -> bool:
        return self.mode.writes_allowed

    @property
    def environment(self) -> str:
        """Human-readable label for buildium_health."""
        if self.mode is DeploymentMode.SANDBOX:
            return "sandbox"
        if self.mode is DeploymentMode.PRODUCTION_READONLY:
            return "PRODUCTION (read-only)"
        if self.mode is DeploymentMode.PRODUCTION_READONLY_FILES:
            return "PRODUCTION (read-only + file downloads)"
        return "PRODUCTION (writes enabled)"

    @property
    def download_requests_allowed(self) -> bool:
        return self.mode.download_requests_allowed


def parse_deployment_mode(raw: str | None) -> tuple[DeploymentMode, str]:
    """Turn the env var's value into a mode, reporting where it came from.

    Returns ``(mode, source)`` where source is either ``"default"`` or the
    variable's name — so an operator reading the startup banner can tell "I
    never set that" apart from "that is what I asked for".

    Unset, empty, or whitespace means sandbox. An MCP client that emits
    ``"BUILDIUM_DEPLOYMENT_MODE": ""`` must not thereby escalate, and must not
    fail to start either.

    An unrecognized value is a hard error, unlike BUILDIUM_WRITE_MODE which
    silently falls back. That fallback is safe because it can only narrow; here
    a typo'd "production-readonlyy" silently becoming sandbox would look like
    an outage, and the natural way to "fix" an outage is to escalate.
    """
    if raw is None or not raw.strip():
        return DeploymentMode.SANDBOX, "default"

    # Forgiving about form, strict about meaning.
    normalized = raw.strip().lower().replace("_", "-")
    try:
        return DeploymentMode(normalized), MODE_ENV_VAR
    except ValueError:
        valid = ", ".join(m.value for m in DeploymentMode)
        raise ConfigError(
            f"{MODE_ENV_VAR}={raw!r} is not a valid deployment mode.\n"
            f"Valid values: {valid}.\n"
            "Leave it unset for sandbox, which is the safe default."
        ) from None


def _redact(value: str) -> str:
    """Never echo a secret. Show only enough to tell two keys apart."""
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-2:]} (len {len(value)})"


def _check_host(host: str, mode: DeploymentMode) -> None:
    """Refuse a base URL the current mode does not sanction.

    Sandbox hosts are acceptable in every mode — pointing a production-mode
    server at the sandbox is strictly safer, not less safe. Production hosts
    require one of the two production modes.
    """
    if host in SANDBOX_HOSTS:
        return

    if host in PRODUCTION_HOSTS:
        if mode.is_production:
            return
        raise ConfigError(
            f"Refusing to start against production host {host!r}.\n"
            f"{MODE_ENV_VAR} is {mode.value!r}, which only sanctions the "
            f"sandbox. To reach production set {MODE_ENV_VAR} to one of: "
            "production-readonly, production-readonly-files, production-write.\n"
            "Reaching production deliberately takes both that variable and a "
            "production BUILDIUM_BASE_URL; neither alone is enough."
        )

    raise ConfigError(
        f"Refusing to start against unrecognized host {host!r}. "
        f"Approved hosts: {', '.join(sorted(SANDBOX_HOSTS | PRODUCTION_HOSTS))}. "
        "Add it to SANDBOX_HOSTS or PRODUCTION_HOSTS in config.py if it is real."
    )


def load_config() -> Config:
    env_files_loaded: list[str] = []
    for candidate in paths.env_file_candidates():
        if candidate.is_file():
            load_dotenv(candidate)
            env_files_loaded.append(str(candidate))

    mode, mode_source = parse_deployment_mode(os.getenv(MODE_ENV_VAR))

    base_url = os.getenv("BUILDIUM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    # The spec's paths already carry /v1; a base URL ending in /v1 would double it.
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    host = urlparse(base_url).netloc.lower()
    if not host:
        raise ConfigError(f"BUILDIUM_BASE_URL is not a valid URL: {base_url!r}")

    _check_host(host, mode)

    client_id = os.getenv("BUILDIUM_CLIENT_ID", "").strip()
    client_secret = os.getenv("BUILDIUM_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ConfigError(
            "BUILDIUM_CLIENT_ID and BUILDIUM_CLIENT_SECRET must both be set "
            f"(got id={_redact(client_id)}, secret={_redact(client_secret)}). "
            "Pass them in your MCP client's env block, or put them in a .env "
            "file — see .env.example and buildium_health for the search path."
        )

    spec_path = paths.resolve_spec_path()
    if not spec_path.is_file():
        raise ConfigError(f"OpenAPI spec not found at {spec_path}")

    run_log, artifact_log, log_dir_error = paths.resolve_log_paths()

    return Config(
        base_url=base_url,
        client_id=client_id,
        client_secret=client_secret,
        spec_path=spec_path,
        run_log=run_log,
        artifact_log=artifact_log,
        fixture_prefix=os.getenv("BUILDIUM_FIXTURE_PREFIX", "ZZ-MCPTEST-"),
        mode=mode,
        mode_source=mode_source,
        log_dir_error=log_dir_error,
        env_files_loaded=tuple(env_files_loaded),
    )
