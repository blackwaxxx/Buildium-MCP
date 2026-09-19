"""HTTP client for the Buildium API: auth, error mapping, and audit logging.

Buildium authenticates with two static headers — there is no OAuth flow, no
token endpoint, and no refresh. Errors are translated into messages a model can
act on, because a raw traceback tells it nothing about which field was wrong.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from . import __version__
from .config import (
    PRODUCTION_HOSTS,
    SANDBOX_HOSTS,
    Config,
    DeploymentMode,
    is_download_request_path,
    is_upload_request_path,
    request_permitted,
)

# Query params Buildium requires but does not declare. Every entry here was
# found by reading a 422 body during the coverage walk — the spec marks none of
# them required, so describe_endpoint cannot tell a caller about them.
KNOWN_REQUIRED_HINTS: dict[str, str] = {
    "/v1/bills": "requires BOTH 'frompaiddate' and 'topaiddate' — the default "
                 "PaidStatus filter returns paid bills, and those need a paid-date "
                 "window. Neither is marked required in the spec",
    "/v1/inventoryassets": "requires 'entitytype' (Rental or Association) and "
                           "'entityid'; neither is marked required in the spec",
    "/v1/inventorystorages": "requires 'entitytype' (Rental or Association) and "
                             "'entityid'; neither is marked required in the spec",
    "/v1/leases/renewals": "requires 'esignaturestatuses' with at least one value",
}

# Buildium rejects any date-range filter spanning more than a year, and says so
# only in the 422 body. Callers reach for a wide window precisely when they want
# everything, so this is a common first failure.
DATE_RANGE_CAP_HINT = (
    "Buildium caps every date-range filter at 365 days. Narrow the window to a "
    "year or less and page through longer periods a year at a time."
)


class ReadOnlyViolation(RuntimeError):
    """A mutating request was stopped before a socket was opened.

    Raised in the read-only deployment modes. This is not a policy check that a
    caller can talk its way past — see ReadOnlyTransportGuard.
    """


def _wire_path(request: httpx.Request) -> str:
    """The exact bytes httpx will send as the request target, minus the query.

    Deliberately ``raw_path`` and not ``url.path``: raw_path is what goes on the
    wire and is still percent-encoded, so ``%2f``, ``%2e%2e`` and ``%00`` cannot
    masquerade as separators or dot segments *after* the allowlist has approved
    the string. ``url.path`` is percent-decoded, which would turn
    ``%2f..%2fleases`` into ``/../leases`` inside a value we had already judged
    safe.
    """
    raw = request.url.raw_path.split(b"?", 1)[0]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        # Never matches the anchored ASCII allowlist, so this fails closed.
        return "\ufffd"


class ReadOnlyTransportGuard(httpx.AsyncBaseTransport):
    """Refuse every mutating HTTP method at the transport layer.

    This is what makes the read-only modes structural rather than advisory. A
    transport is the last code that runs before httpx opens a socket, so this
    guard cannot be bypassed by calling ``client.post()`` directly, by building
    an ``httpx.Request`` by hand and calling ``send()``, or by reaching past
    BuildiumClient entirely. Every route to the network passes through here.

    The host and scheme are checked for *every* request, not only mutating
    ones, because an *absolute* URL handed to httpx retargets the request away
    from base_url — and the client's default headers carry the API credentials.
    Without that check a caller who reached the underlying client could aim an
    allowlisted download path, or a credentialed GET, at a host of their
    choosing.

    Methods are judged by allowlist (config.SAFE_METHODS), so an unknown or
    malformed verb is refused rather than waved through as "not a write".
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        mode: DeploymentMode,
        allowed_hosts: frozenset[str],
    ):
        self._inner = inner
        self._mode = mode
        self._allowed_hosts = allowed_hosts

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        method = request.method.strip().upper()
        host = (request.url.host or "").lower()
        path = _wire_path(request)
        if request.url.scheme != "https" or host not in self._allowed_hosts:
            raise ReadOnlyViolation(
                f"{method} {path} blocked: {request.url.scheme}://{host} is not "
                "an approved Buildium host over https. No request was sent."
            )
        if not request_permitted(self._mode, method, path):
            hint = (
                " Buildium issues file downloads as a POST; set "
                "BUILDIUM_DEPLOYMENT_MODE=production-readonly-files to permit "
                "those seven endpoints and nothing else."
                if method == "POST" and is_download_request_path(path)
                else ""
            )
            raise ReadOnlyViolation(
                f"{method} {path} blocked: this server is running in "
                f"{self._mode.value} mode, where only GET, HEAD and OPTIONS "
                f"leave the process. Refused at the transport layer; no request "
                f"was sent.{hint}"
            )
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class BuildiumError(RuntimeError):
    """An API error already translated into something actionable."""

    def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


@dataclass
class Response:
    status: int
    data: Any
    headers: dict[str, str]


class BuildiumClient:
    def __init__(self, config: Config):
        self.config = config
        transport: httpx.AsyncBaseTransport | None = None
        if not config.writes_allowed:
            transport = ReadOnlyTransportGuard(
                httpx.AsyncHTTPTransport(),
                mode=config.mode,
                allowed_hosts=SANDBOX_HOSTS | PRODUCTION_HOSTS,
            )
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url=config.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "x-buildium-client-id": config.client_id,
                "x-buildium-client-secret": config.client_secret,
                "Accept": "application/json",
                "User-Agent": f"buildium-mcp/{__version__}",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- audit -------------------------------------------------------------

    def _audit(self, record: dict[str, Any]) -> None:
        """Append one JSON line per request. Secrets are never included."""
        if self.config.run_log is None:
            # Audit logging is off, or the state directory is unwritable. The
            # reason is on Config.log_dir_error and reported by buildium_health,
            # so this is visible rather than merely silent.
            return
        record["ts"] = datetime.now(timezone.utc).isoformat()
        try:
            with self.config.run_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            # An audit failure must not take down the call it was recording.
            pass

    # -- request -----------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: Any = None,
        max_retries: int = 2,
    ) -> Response:
        method = method.strip().upper()
        if not path.startswith("/"):
            path = "/" + path

        # Advisory, not authoritative: the transport guard below is the real
        # boundary and sees the normalized wire path. This runs on the caller's
        # raw string purely to produce a clean message and an audit record, so
        # it may be marginally stricter — refusing odd input early is fine.
        if not request_permitted(self.config.mode, method, path):
            self._audit({"method": method, "path": path, "refused": "read_only_mode"})
            hint = (
                " Buildium issues file downloads as a POST; set "
                "BUILDIUM_DEPLOYMENT_MODE=production-readonly-files to permit those."
                if method == "POST" and is_download_request_path(path)
                else ""
            )
            raise BuildiumError(
                f"{method} {path} refused: BUILDIUM_DEPLOYMENT_MODE is "
                f"{self.config.mode.value!r}, which permits reads only. Writes are "
                f"blocked at the transport layer, so no request was sent.{hint}",
                status=None,
            )

        params = {k: v for k, v in (query or {}).items() if v is not None}
        attempt = 0

        while True:
            attempt += 1
            started = time.monotonic()
            try:
                resp = await self._client.request(
                    method, path, params=params or None, json=body
                )
            except ReadOnlyViolation as exc:
                self._audit({"method": method, "path": path, "refused": "transport_guard"})
                raise BuildiumError(str(exc), status=None) from exc
            except httpx.RequestError as exc:
                self._audit(
                    {
                        "method": method,
                        "path": path,
                        "query": params,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                raise BuildiumError(
                    f"Network error calling {method} {path}: {exc}. "
                    "Check connectivity and that the base URL is reachable."
                ) from exc

            elapsed_ms = round((time.monotonic() - started) * 1000)

            try:
                data: Any = resp.json() if resp.content else None
            except ValueError:
                data = resp.text

            self._audit(
                {
                    "method": method,
                    "path": path,
                    "query": params,
                    "body": body,
                    "status": resp.status_code,
                    "elapsed_ms": elapsed_ms,
                    "attempt": attempt,
                    "response": data if resp.status_code >= 400 else "<ok>",
                }
            )

            # Rate limited — honour Retry-After, then retry.
            if resp.status_code == 429 and attempt <= max_retries:
                retry_after = float(resp.headers.get("Retry-After", "2") or 2)
                await _sleep(min(retry_after, 30.0))
                continue

            if resp.status_code >= 400:
                raise self._translate(resp.status_code, data, method, path)

            return Response(
                status=resp.status_code,
                data=data,
                headers=dict(resp.headers),
            )

    # -- pagination --------------------------------------------------------

    async def get_all_pages(
        self,
        path: str,
        query: dict[str, Any] | None = None,
        *,
        page_size: int = 100,
        max_records: int = 1000,
    ) -> tuple[list[Any], bool]:
        """Follow offset/limit until the collection is exhausted.

        Returns (records, truncated). `truncated` is True when the cap was hit
        with more still available — an honest signal that the answer is
        partial, which matters more than the records themselves if a caller is
        about to count something.

        Buildium reports no total, so the end of a collection is detected by a
        short page. A collection whose size is an exact multiple of page_size
        therefore costs one extra request, which is the correct trade: the
        alternative is silently stopping one page early.
        """
        records: list[Any] = []
        offset = 0
        while len(records) < max_records:
            limit = min(page_size, max_records - len(records))
            resp = await self.request(
                "GET", path, query={**(query or {}), "limit": limit, "offset": offset}
            )
            page = resp.data if isinstance(resp.data, list) else []
            records.extend(page)
            if len(page) < limit:
                return records, False
            offset += len(page)

        # We stopped at the cap. One more request decides whether that
        # actually truncated anything, so the caller is never left guessing.
        probe = await self.request("GET", path, query={**(query or {}), "limit": 1,
                                                       "offset": offset})
        more = bool(probe.data if isinstance(probe.data, list) else [])
        return records, more

    # -- files: Buildium's two-step signed-URL flow ------------------------
    #
    # Neither upload nor download moves bytes through the Buildium API. Both
    # hand back a short-lived URL on separate storage infrastructure, and the
    # caller transfers the bytes there directly.
    #
    #   upload    POST .../files/uploads {metadata}  -> {UploadUrl, Headers, ...}
    #             PUT the raw bytes to UploadUrl, sending every entry of
    #             Headers as an actual HTTP header. UploadUrl is an AWS S3
    #             presigned PUT whose X-Amz-SignedHeaders covers each
    #             x-amz-meta-* header, so omitting even one — or sending the
    #             bytes as multipart/form-data instead of raw — fails with
    #             SignatureDoesNotMatch.
    #
    #   download  POST .../downloadrequest           -> {DownloadUrl}
    #             GET DownloadUrl. Expires after five minutes.
    #
    # The signed URL points at third-party storage, so the Buildium client
    # id and secret must never be attached to it. _transfer_client below is a
    # bare client with no default headers for exactly that reason; sending
    # our credentials to a host named by an API response would leak them to
    # wherever that response pointed.

    # The two helpers below take their request path from the MCP caller. Each
    # is confined to the endpoints it exists for, in every deployment mode:
    # otherwise "download this file" is an arbitrary empty-body POST and
    # "upload this file" an arbitrary POST with a metadata body, in any mode
    # where writes are allowed at all — skipping the spec lookup and the
    # fixture tracker that call_endpoint applies. The check happens before
    # any request is built, so nothing reaches the network.

    @staticmethod
    def _check_signed_url(url: str, purpose: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise BuildiumError(
                f"Refusing to {purpose} over {parsed.scheme or 'an unknown scheme'}: "
                f"the {purpose} URL returned by Buildium is not https."
            )
        if not parsed.netloc:
            raise BuildiumError(f"Buildium returned an unusable {purpose} URL.")

    async def upload_file(
        self,
        request_path: str,
        metadata: dict[str, Any],
        file_bytes: bytes,
        file_name: str,
    ) -> dict[str, Any]:
        """Run both halves of an upload. Returns the ticket plus the storage
        response status, so a caller can prove the bytes actually landed."""
        request_path = _confined(request_path, is_upload_request_path, "upload")
        ticket = await self.request("POST", request_path, body=metadata)
        data = ticket.data if isinstance(ticket.data, dict) else {}
        upload_url = data.get("UploadUrl")
        if not upload_url:
            raise BuildiumError(
                f"POST {request_path} returned no UploadUrl, so there is nowhere "
                f"to send the bytes. Response keys: {sorted(data)}",
                status=ticket.status,
                payload=data,
            )
        self._check_signed_url(upload_url, "upload")

        signed_headers = {k: str(v) for k, v in (data.get("Headers") or {}).items()}
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as transfer:
            resp = await transfer.put(
                upload_url, content=file_bytes, headers=signed_headers
            )

        self._audit({
            "method": "PUT",
            "path": f"<signed upload url for {request_path}>",
            "status": resp.status_code,
            "bytes": len(file_bytes),
        })
        if resp.status_code >= 400:
            raise BuildiumError(
                f"Buildium accepted the upload request but the storage host "
                f"rejected the bytes with HTTP {resp.status_code}. "
                "SignatureDoesNotMatch here means the signed headers were not "
                "reproduced exactly — every entry of the ticket's Headers must "
                "be sent verbatim as an HTTP header. "
                f"{resp.text[:300]}",
                status=resp.status_code,
            )
        return {
            "physical_file_name": data.get("PhysicalFileName"),
            "storage_status": resp.status_code,
            "bytes_sent": len(file_bytes),
        }

    async def download_file(self, request_path: str) -> tuple[bytes, str]:
        """Run both halves of a download. Returns (bytes, content-type)."""
        request_path = _confined(request_path, is_download_request_path, "download")
        ticket = await self.request("POST", request_path)
        data = ticket.data if isinstance(ticket.data, dict) else {}
        url = data.get("DownloadUrl")
        if not url:
            raise BuildiumError(
                f"POST {request_path} returned no DownloadUrl. "
                f"Response keys: {sorted(data)}",
                status=ticket.status,
                payload=data,
            )
        self._check_signed_url(url, "download")

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as transfer:
            resp = await transfer.get(url, follow_redirects=True)

        self._audit({
            "method": "GET",
            "path": f"<signed download url for {request_path}>",
            "status": resp.status_code,
            "bytes": len(resp.content),
        })
        if resp.status_code >= 400:
            raise BuildiumError(
                f"The download URL Buildium issued returned HTTP "
                f"{resp.status_code}. These URLs expire after five minutes; "
                "request a fresh one and retry.",
                status=resp.status_code,
            )
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    # -- error translation -------------------------------------------------

    def _translate(self, status: int, data: Any, method: str, path: str) -> BuildiumError:
        detail = ""
        if isinstance(data, dict):
            user_msg = data.get("UserMessage") or data.get("Message") or ""
            errors = data.get("Errors") or []
            if isinstance(errors, list) and errors:
                parts = [
                    f"{e.get('Key')}: {e.get('Value')}"
                    for e in errors
                    if isinstance(e, dict)
                ]
                detail = f"{user_msg} [{'; '.join(parts)}]" if parts else user_msg
            else:
                detail = user_msg
        elif data:
            detail = str(data)[:400]

        base = f"{method} {path} failed with HTTP {status}"

        if status == 401:
            return BuildiumError(
                f"{base}: credentials rejected. Verify BUILDIUM_CLIENT_ID and "
                "BUILDIUM_CLIENT_SECRET, and that the key belongs to this "
                "environment — sandbox keys do not work against production and "
                "vice versa.",
                status=status,
                payload=data,
            )
        if status == 403:
            return BuildiumError(
                f"{base}: authenticated but not authorized. The API key exists "
                "but lacks the resource scope for this endpoint. Enable it in "
                "Buildium under Settings -> Developer Tools -> (your key) -> "
                f"resource permissions. {detail}",
                status=status,
                payload=data,
            )
        if status == 404:
            return BuildiumError(
                f"{base}: not found. Either the record does not exist or the "
                f"path is wrong — use search_endpoints to confirm. {detail}",
                status=status,
                payload=data,
            )
        if status in (400, 422):
            hint = KNOWN_REQUIRED_HINTS.get(path, "")
            hint_text = f" Hint: this endpoint {hint}." if hint else ""
            if "365 days" in detail or "time range must be" in detail:
                hint_text += f" Hint: {DATE_RANGE_CAP_HINT}"
            return BuildiumError(
                f"{base}: request validation failed. {detail}{hint_text} "
                "Call describe_endpoint to see required fields and types.",
                status=status,
                payload=data,
            )
        if status == 429:
            return BuildiumError(
                f"{base}: rate limited and retries exhausted. Back off and retry.",
                status=status,
                payload=data,
            )
        if status >= 500:
            return BuildiumError(
                f"{base}: Buildium server error. This is upstream, not a problem "
                f"with the request. {detail}",
                status=status,
                payload=data,
            )
        return BuildiumError(f"{base}. {detail}", status=status, payload=data)


def _confined(path: str, allowed, purpose: str) -> str:
    """Normalize a caller-supplied path and refuse it unless `allowed` says yes."""
    if not path.startswith("/"):
        path = "/" + path
    if not allowed(path):
        raise BuildiumError(
            f"{path} is not a Buildium {purpose}-request endpoint, so "
            f"{purpose}_file will not POST to it. This helper is confined to the "
            f"seven {purpose} endpoints in every deployment mode; for anything "
            "else use call_endpoint, which applies the write guardrails.",
            status=None,
        )
    return path


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
