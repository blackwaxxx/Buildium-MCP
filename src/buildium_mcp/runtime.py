"""Deferred, staged startup.

The server used to build its config, spec index and HTTP client at import time.
That is fine when the only user is the person who wrote it — and hostile to
everyone else, because a missing API key then kills the process during import
and the operator sees a Python traceback in a log they may never read, rather
than a tool telling them what to set.

So startup happens on first use, in four stages that fail independently:

    A  mode, paths, env files      fails only on a malformed mode value
    B  Config                      fails on missing credentials or a bad host
    C  SpecIndex                   fails on a missing or corrupt spec
    D  client + fixture tracker    needs B

C depends on A but *not* on B. That is deliberate and worth the small amount of
plumbing it costs: with no credentials configured at all, the four spec-only
tools still work, so an agent can still explore the API surface and tell the
user exactly what is missing instead of failing blank.

Both success and failure are memoized. Without that, a broken configuration is
re-attempted once per tool call, which turns one clear error into nineteen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import paths
from .client import BuildiumClient
from .config import (
    MODE_ENV_VAR,
    Config,
    ConfigError,
    DeploymentMode,
    load_config,
    parse_deployment_mode,
)
from .guards import FixtureTracker, write_mode
from .spec import SpecIndex, load_index


class StartupError(RuntimeError):
    """Configuration is incomplete. Carries the fix, not just the complaint."""

    def __init__(self, message: str, *, remedy: str, stage: str):
        super().__init__(message)
        self.remedy = remedy
        self.stage = stage


@dataclass(frozen=True)
class Runtime:
    config: Config
    index: SpecIndex
    client: BuildiumClient
    tracker: FixtureTracker


_index: SpecIndex | None = None
_index_error: StartupError | None = None
_runtime: Runtime | None = None
_runtime_error: StartupError | None = None


def reset() -> None:
    """Drop every memoized stage. Tests only."""
    global _index, _index_error, _runtime, _runtime_error
    _index = _index_error = _runtime = _runtime_error = None


def get_index() -> SpecIndex:
    """Stages A + C. Needs no credentials."""
    global _index, _index_error
    if _index is not None:
        return _index
    if _index_error is not None:
        raise _index_error

    try:
        spec_path = paths.resolve_spec_path()
        if not spec_path.is_file():
            raise StartupError(
                f"OpenAPI spec not found at {spec_path}",
                remedy=(
                    "The spec ships inside this package, so this usually means a "
                    "broken install. Reinstall buildium-mcp, or point "
                    "BUILDIUM_SPEC_PATH at a copy of the Buildium OpenAPI JSON."
                ),
                stage="spec",
            )
        _index = load_index(spec_path)
        return _index
    except StartupError as exc:
        _index_error = exc
        raise
    except Exception as exc:  # malformed JSON, unreadable file
        _index_error = StartupError(
            f"Could not load the OpenAPI spec: {exc}",
            remedy="Check BUILDIUM_SPEC_PATH, or reinstall buildium-mcp.",
            stage="spec",
        )
        raise _index_error from exc


def get_runtime() -> Runtime:
    """Stages A + B + C + D. Everything that talks to Buildium needs this."""
    global _runtime, _runtime_error
    if _runtime is not None:
        return _runtime
    if _runtime_error is not None:
        raise _runtime_error

    try:
        index = get_index()
        try:
            config = load_config()
        except ConfigError as exc:
            raise StartupError(
                str(exc),
                remedy=_remedy_for(str(exc)),
                stage=_stage_for(str(exc)),
            ) from exc
        _runtime = Runtime(
            config=config,
            index=index,
            client=BuildiumClient(config),
            tracker=FixtureTracker(config),
        )
        return _runtime
    except StartupError as exc:
        _runtime_error = exc
        raise


def _stage_for(message: str) -> str:
    """Name the thing that is actually wrong, not the stage that noticed."""
    if "host" in message or "not a valid URL" in message:
        return "base_url"
    return "credentials"


def _remedy_for(message: str) -> str:
    if "CLIENT_ID" in message or "CLIENT_SECRET" in message:
        return (
            "Set BUILDIUM_CLIENT_ID and BUILDIUM_CLIENT_SECRET. Pass them in your "
            "MCP client's env block, or put them in "
            f"{paths.config_dir() / '.env'}. Create a key in Buildium under "
            "Settings > Developer Tools (requires a Premium subscription with the "
            "Open API enabled)."
        )
    if "production host" in message:
        return (
            "Either point BUILDIUM_BASE_URL at the sandbox, or set "
            "BUILDIUM_DEPLOYMENT_MODE to production-readonly, "
            "production-readonly-files, or production-write."
        )
    if "unrecognized host" in message:
        return "BUILDIUM_BASE_URL must be https://apisandbox.buildium.com or https://api.buildium.com."
    return "See the README for configuration."


@dataclass(frozen=True)
class StartupStatus:
    """A description of startup that is safe to render even when it failed."""

    mode: DeploymentMode
    mode_source: str
    ok: bool
    stage: str | None
    error: str | None
    remedy: str | None
    checks: dict[str, str]
    base_url: str | None
    spec_path: str
    operations: int | None
    run_log: str | None
    log_dir_error: str | None
    env_files_loaded: tuple[str, ...]
    write_mode: str
    writes_allowed: bool
    download_requests_allowed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "deployment_mode": self.mode.value,
            "deployment_mode_source": self.mode_source,
            "environment": _environment_label(self.mode),
            "writes_allowed": self.writes_allowed,
            "download_requests_allowed": self.download_requests_allowed,
            "write_mode": self.write_mode,
            "base_url": self.base_url,
            "spec": self.spec_path,
            "operations_indexed": self.operations,
            "audit_log": self.run_log,
            "audit_log_disabled_reason": self.log_dir_error,
            "env_files_loaded": list(self.env_files_loaded),
            "checks": self.checks,
        }


def _environment_label(mode: DeploymentMode) -> str:
    if mode is DeploymentMode.SANDBOX:
        return "sandbox"
    if mode is DeploymentMode.PRODUCTION_READONLY:
        return "PRODUCTION (read-only)"
    if mode is DeploymentMode.PRODUCTION_READONLY_FILES:
        return "PRODUCTION (read-only + file downloads)"
    return "PRODUCTION (writes enabled)"


def startup_status() -> StartupStatus:
    """Describe startup without raising, whatever state it is in.

    This is what buildium_health reports and what the banner renders. It must
    never raise: a server that cannot say why it is broken is worse than one
    that is broken.
    """
    import os

    checks: dict[str, str] = {}

    try:
        mode, mode_source = parse_deployment_mode(os.getenv(MODE_ENV_VAR))
        checks["mode"] = "ok"
    except ConfigError as exc:
        return StartupStatus(
            mode=DeploymentMode.SANDBOX, mode_source="default", ok=False,
            stage="mode", error=str(exc),
            remedy="Set BUILDIUM_DEPLOYMENT_MODE to one of: "
                   + ", ".join(m.value for m in DeploymentMode),
            checks={"mode": str(exc)}, base_url=None,
            spec_path=str(paths.resolve_spec_path()), operations=None,
            run_log=None, log_dir_error=None, env_files_loaded=(),
            write_mode=write_mode(), writes_allowed=False,
            download_requests_allowed=False,
        )

    spec_path = paths.resolve_spec_path()
    operations: int | None = None
    try:
        operations = len(get_index().endpoints)
        checks["spec"] = f"ok ({operations} operations)"
    except StartupError as exc:
        checks["spec"] = str(exc)

    run_log, _artifact, log_dir_error = paths.resolve_log_paths()
    checks["audit_log"] = log_dir_error or "ok"

    try:
        runtime = get_runtime()
    except StartupError as exc:
        checks.setdefault(exc.stage, str(exc))
        return StartupStatus(
            mode=mode, mode_source=mode_source, ok=False, stage=exc.stage,
            error=str(exc), remedy=exc.remedy, checks=checks,
            base_url=os.getenv("BUILDIUM_BASE_URL"), spec_path=str(spec_path),
            operations=operations, run_log=str(run_log) if run_log else None,
            log_dir_error=log_dir_error, env_files_loaded=(),
            write_mode=write_mode(), writes_allowed=mode.writes_allowed,
            download_requests_allowed=mode.download_requests_allowed,
        )

    config = runtime.config
    checks["credentials"] = "ok"
    return StartupStatus(
        mode=config.mode, mode_source=config.mode_source, ok=True, stage=None,
        error=None, remedy=None, checks=checks, base_url=config.base_url,
        spec_path=str(config.spec_path), operations=operations,
        run_log=str(config.run_log) if config.run_log else None,
        log_dir_error=config.log_dir_error,
        env_files_loaded=config.env_files_loaded,
        write_mode=write_mode(), writes_allowed=config.writes_allowed,
        download_requests_allowed=config.download_requests_allowed,
    )
