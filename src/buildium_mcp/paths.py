"""Where this server reads its configuration and writes its logs.

Every path here used to be derived from a repo checkout. That worked for an
editable install and broke the moment the package was installed from a wheel,
because ``Path(__file__).parents[2]`` then points inside the interpreter's
library directory. Three things depended on it — the OpenAPI spec, the ``.env``
file, and the two audit logs — and all three failed silently or fatally.

So paths are resolved two ways now, by kind:

  * the spec ships *inside* the package, addressed through importlib.resources,
    so one code path serves both a wheel and an editable checkout;
  * ``.env`` and the logs live in the user's own config/state directories,
    because a package directory is not ours to write to and may be read-only.

Every location is overridable by an environment variable, since the people most
likely to need a different layout (containers, CI, multi-tenant hosts) are also
the least likely to be able to change the code.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
from typing import IO

from platformdirs import user_config_dir, user_downloads_dir, user_state_dir

APP_NAME = "buildium-mcp"

SPEC_FILENAME = "buildium-openapi.json"

# Sentinel accepted by BUILDIUM_RUN_LOG / BUILDIUM_ARTIFACT_LOG to mean
# "write nothing at all", for people who would rather have no audit trail than
# one they did not ask for.
LOG_OFF = {"off", "none", "disabled", "/dev/null"}


def _env_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw).expanduser() if raw else None


def config_dir() -> Path:
    """Where ``.env`` is looked for. Holds secrets; hence config, not state."""
    override = _env_path("BUILDIUM_CONFIG_DIR")
    if override is not None:
        return override
    return Path(user_config_dir(APP_NAME, appauthor=False))


def state_dir() -> Path:
    """Where the audit logs go. State rather than config: derived, not authored."""
    override = _env_path("BUILDIUM_STATE_DIR")
    if override is not None:
        return override
    return Path(user_state_dir(APP_NAME, appauthor=False))


def download_dir() -> Path:
    """The one folder buildium_download_file may write into.

    The tool used to write wherever it was told. A file a tenant uploaded
    through the portal, plus an instruction planted in a work order, was then
    enough to overwrite ~/.zshrc or drop a LaunchAgent. Confining writes to a
    single folder is the structural fix; BUILDIUM_DOWNLOAD_DIR moves it.
    """
    override = _env_path("BUILDIUM_DOWNLOAD_DIR")
    if override is not None:
        return override
    return Path(user_downloads_dir()) / "Buildium"


def open_private_append(path: Path) -> IO[str]:
    """Open a log for appending, readable and writable by its owner only.

    The audit log records request bodies — tenant names, amounts — and was
    created 0644 under the umask. On macOS the enclosing ~/Library is private
    anyway; on Linux ~/.local/state usually is not, so other local users could
    read it. A file an earlier version created is tightened here too.
    """
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    make_private(fd)
    return os.fdopen(fd, "a", encoding="utf-8")


def make_private(fd: int) -> None:
    """Drop group and other permissions from an open file, where POSIX
    permissions exist. Windows has none to tighten."""
    try:
        if os.fstat(fd).st_mode & 0o077:
            os.fchmod(fd, 0o600)
    except (AttributeError, NotImplementedError, OSError):
        pass


def packaged_spec_path() -> Path:
    """The OpenAPI spec that ships with this package.

    ``resources.files`` returns a Traversable, which is a real filesystem path
    for a normal wheel or editable install. It would not be for a zipimported
    one — this project has never supported that, and the spec is 2.7MB, so
    unpacking it at runtime would be worse than the limitation.
    """
    return Path(str(resources.files("buildium_mcp") / "specs" / SPEC_FILENAME))


def resolve_spec_path() -> Path:
    """The spec to load: an explicit override, else the packaged copy.

    BUILDIUM_SPEC_PATH exists so a user can point at a newer spec than the one
    this release vendored, without waiting for a release.
    """
    override = _env_path("BUILDIUM_SPEC_PATH")
    return override if override is not None else packaged_spec_path()


def checkout_root() -> Path | None:
    """The repository root, when running from a source checkout.

    A checkout is recognized by this module's own position: it must sit at
    ``<root>/src/buildium_mcp/``, with a pyproject.toml at ``<root>``. In a
    wheel the package's parent is site-packages, never ``src``, so this returns
    None and the caller falls through to the user's config directory.

    It used to search upward for any directory holding a pyproject.toml and a
    ``src/``. That also matched every project whose virtualenv this package was
    installed into — ``~/project/.venv/lib/.../site-packages`` has ``~/project``
    above it — and loaded that unrelated project's .env as if it were ours.

    This exists so that a server launched from a checkout by an MCP client —
    which sets the working directory to whatever it likes — still finds the
    checkout's own .env.
    """
    src_dir = Path(__file__).resolve().parent.parent
    root = src_dir.parent
    if src_dir.name == "src" and (root / "pyproject.toml").is_file():
        return root
    return None


def env_file_candidates() -> list[Path]:
    """``.env`` locations in descending priority.

    A file never overwrites a variable that is already set, so these must be
    loaded in this order for the priority to mean anything. The real process
    environment outranks all of them, which is the documented way an MCP
    client should pass credentials.

    The working directory is deliberately not searched. An MCP client starts
    the server wherever it likes — Claude Code uses the open project — so an
    upward search from there read whatever .env that project had, and ranked
    it above the user's own configuration. A developer in a checkout loses
    nothing: the checkout's root is found from this file's location instead.
    """
    candidates: list[Path] = []

    explicit = _env_path("BUILDIUM_ENV_FILE")
    if explicit is not None:
        candidates.append(explicit)

    root = checkout_root()
    if root is not None:
        candidates.append(root / ".env")

    candidates.append(config_dir() / ".env")

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        resolved = path.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def resolve_log_paths() -> tuple[Path | None, Path | None, str | None]:
    """Return ``(run_log, artifact_log, disabled_reason)``.

    A server that cannot write its audit log must still be able to read
    Buildium data — an unwritable state directory is a packaging detail, not a
    reason to deny someone their own records. But the failure has to be
    *visible*: the previous code swallowed OSError at every write site, so a
    broken audit trail looked exactly like a working one. Returning None with a
    reason lets buildium_health say so out loud.
    """
    run_override = os.getenv("BUILDIUM_RUN_LOG", "").strip()
    artifact_override = os.getenv("BUILDIUM_ARTIFACT_LOG", "").strip()

    if run_override.lower() in LOG_OFF and artifact_override.lower() in LOG_OFF:
        return None, None, "disabled by BUILDIUM_RUN_LOG/BUILDIUM_ARTIFACT_LOG"

    directory = state_dir()
    try:
        # 0o700 applies only if this call creates it; a directory the
        # user chose already has the permissions they gave it.
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        return None, None, f"cannot create {directory}: {exc.strerror or exc}"

    if not os.access(directory, os.W_OK):
        return None, None, f"{directory} is not writable"

    run_log: Path | None
    artifact_log: Path | None

    if run_override.lower() in LOG_OFF:
        run_log = None
    elif run_override:
        run_log = Path(run_override).expanduser()
    else:
        run_log = directory / "run.log"

    if artifact_override.lower() in LOG_OFF:
        artifact_log = None
    elif artifact_override:
        artifact_log = Path(artifact_override).expanduser()
    else:
        artifact_log = directory / "created-records.log"

    return run_log, artifact_log, None
