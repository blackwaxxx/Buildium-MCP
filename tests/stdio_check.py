"""Drive the server over real stdio JSON-RPC, the way an MCP client does.

This proves the transport works end to end — not just that the Python functions
are callable. Run: .venv/bin/python tests/stdio_check.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"

# How long to wait for Buildium to finalize an uploaded file record. See the
# comment at the poll site.
UPLOAD_POLL_ATTEMPTS = 10
UPLOAD_POLL_INTERVAL_S = 3


class StdioClient:
    def __init__(self) -> None:
        # Downloads are confined to one folder; give the server a scratch one
        # so the round trip does not land in the real ~/Downloads/Buildium.
        self.download_dir = Path(tempfile.mkdtemp(prefix="buildium-mcp-stdio-"))
        self.proc = subprocess.Popen(
            [str(PY), "-m", "buildium_mcp.server"],
            cwd=str(ROOT),
            env={**os.environ, "BUILDIUM_DOWNLOAD_DIR": str(self.download_dir)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def _send(self, method: str, params: dict | None = None, notify: bool = False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                err = self.proc.stderr.read()
                raise RuntimeError(f"server closed stdout. stderr:\n{err}")
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("id") == self._id:
                return resp

    def initialize(self):
        resp = self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-check", "version": "0"},
            },
        )
        self._send("notifications/initialized", {}, notify=True)
        return resp

    def list_tools(self):
        return self._send("tools/list", {})

    def call(self, name: str, arguments: dict):
        return self._send("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        self.proc.terminate()
        self.proc.wait(timeout=10)


def content_payload(resp: dict):
    """Pull the JSON payload back out of an MCP tool result."""
    result = resp.get("result") or {}
    if "structuredContent" in result:
        return result["structuredContent"]
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except (json.JSONDecodeError, KeyError):
                return block.get("text")
    return result


def main() -> int:
    client = StdioClient()
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
        if not condition:
            failures.append(label)

    def warn(label: str, condition: bool, detail: str = "") -> None:
        """Like check, but a miss is reported and does not fail the run.

        For observations about Buildium's own asynchronous behaviour, which
        this script cannot make deterministic.
        """
        status = "PASS" if condition else "WARN"
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))

    try:
        print("== handshake ==")
        init = client.initialize()
        server_name = (init.get("result", {}).get("serverInfo") or {}).get("name")
        check("initialize", server_name == "buildium_mcp", f"serverInfo.name={server_name!r}")

        print("\n== tools/list ==")
        tools = client.list_tools()
        names = [t["name"] for t in tools.get("result", {}).get("tools", [])]
        print(f"  {len(names)} tools: {', '.join(sorted(names))}")
        check("tool count is small", len(names) <= 20, f"{len(names)} tools")
        for required in ("buildium_search_endpoints", "buildium_describe_endpoint", "buildium_call_endpoint", "buildium_health"):
            check(f"exposes {required}", required in names)

        print("\n== health ==")
        health = content_payload(client.call("buildium_health", {}))
        check("sandbox environment", health.get("environment") == "sandbox", str(health.get("base_url")))
        check("fixtures write mode", health.get("write_mode") == "fixtures")
        check("462 operations indexed", health.get("operations_indexed") == 462)

        print("\n== search / describe ==")
        found = content_payload(client.call("buildium_search_endpoints", {"query": "work orders", "limit": 3}))
        check("search returns hits", found.get("count", 0) > 0, f"{found.get('count')} results")
        desc = content_payload(client.call("buildium_describe_endpoint", {"method": "GET", "path": "/v1/leases"}))
        check("describe resolves params", len(desc.get("parameters", [])) > 0, f"{len(desc.get('parameters', []))} params")
        bad = content_payload(client.call("buildium_describe_endpoint", {"method": "GET", "path": "/v1/nope"}))
        check("unknown path suggests alternatives", bad.get("ok") is False and "did_you_mean" in bad)

        print("\n== reads against sandbox ==")
        rentals = content_payload(client.call("buildium_list_rentals", {"limit": 2}))
        check("list_rentals", rentals.get("ok") is True, f"count={rentals.get('count')}")
        leases = content_payload(client.call("buildium_list_leases", {"limit": 2}))
        check("list_leases", leases.get("ok") is True, f"count={leases.get('count')}")
        gl = content_payload(client.call("buildium_list_gl_accounts", {"limit": 3}))
        check("list_gl_accounts", gl.get("ok") is True, f"count={gl.get('count')}")
        wo = content_payload(client.call("buildium_list_work_orders", {"limit": 2}))
        check("list_work_orders", wo.get("ok") is True, f"count={wo.get('count')}")
        generic = content_payload(client.call("buildium_call_endpoint", {"method": "GET", "path": "/v1/vendors", "query": {"limit": 2}}))
        check("call_endpoint generic GET", generic.get("ok") is True)

        print("\n== error mapping ==")
        bills = content_payload(client.call("buildium_call_endpoint", {"method": "GET", "path": "/v1/bills"}))
        check(
            "422 carries actionable hint",
            bills.get("ok") is False and "Hint" in str(bills.get("error", "")),
            str(bills.get("error", ""))[:90],
        )

        print("\n== write guardrails (refused before any HTTP call) ==")
        unprefixed = content_payload(
            client.call("buildium_call_endpoint", {
                "method": "POST", "path": "/v1/rentals/appliances",
                "body": {"Name": "Regular Fridge", "PropertyId": 1},
            })
        )
        check(
            "unprefixed create refused",
            unprefixed.get("ok") is False and "fixtures" in str(unprefixed.get("error", "")),
        )
        undeleted = content_payload(
            client.call("buildium_call_endpoint", {"method": "DELETE", "path": "/v1/rentals/appliances/999999999"})
        )
        check(
            "delete without confirm refused",
            undeleted.get("ok") is False and "confirm" in str(undeleted.get("error", "")),
            str(undeleted.get("error", ""))[:70],
        )
        unowned = content_payload(
            client.call("buildium_call_endpoint", {
                "method": "DELETE", "path": "/v1/rentals/appliances/999999999", "confirm": True,
            })
        )
        check(
            "delete of unowned record refused",
            unowned.get("ok") is False and "did not create" in str(unowned.get("error", "")),
            str(unowned.get("error", ""))[:70],
        )
        unowned_put = content_payload(
            client.call("buildium_call_endpoint", {
                "method": "PUT", "path": "/v1/rentals/appliances/999999999",
                "body": {"Name": "ZZ-MCPTEST-hijack"},
            })
        )
        check(
            "update of unowned record refused",
            unowned_put.get("ok") is False and "did not create" in str(unowned_put.get("error", "")),
        )

        print("\n== full CRUD on a self-created fixture ==")
        props = content_payload(client.call("buildium_list_rentals", {"limit": 1}))
        property_id = (props.get("data") or [{}])[0].get("Id") if props.get("ok") else None
        check("got a sandbox property to attach to", property_id is not None, f"PropertyId={property_id}")

        if property_id is None:
            failures.append("CRUD chain aborted — no property available")
        else:
            # Unique per run: Buildium rejects duplicates on re-runs.
            import time as _time
            tag = f"ZZ-MCPTEST-appliance-{int(_time.time())}"
            created = content_payload(
                client.call("buildium_call_endpoint", {
                    "method": "POST", "path": "/v1/rentals/appliances",
                    "body": {"Name": tag, "PropertyId": property_id,
                             "Make": "TestCo", "Model": "MCP-1"},
                })
            )
            check("CREATE with fixture prefix", created.get("ok") is True, str(created.get("error", ""))[:140])
            new_id = (created.get("data") or {}).get("Id") if created.get("ok") else None

            if not new_id:
                failures.append("CRUD chain aborted — create failed")
            else:
                print(f"  created appliance id={new_id} name={tag}")
                read_back = content_payload(
                    client.call("buildium_call_endpoint", {"method": "GET", "path": f"/v1/rentals/appliances/{new_id}"})
                )
                check(
                    "READ back created record",
                    read_back.get("ok") is True and (read_back.get("data") or {}).get("Name") == tag,
                    str(read_back.get("error", ""))[:120],
                )
                updated = content_payload(
                    client.call("buildium_call_endpoint", {
                        "method": "PUT", "path": f"/v1/rentals/appliances/{new_id}",
                        "body": {"Name": tag + "-upd", "PropertyId": property_id,
                                 "Make": "TestCo", "Model": "MCP-2"},
                    })
                )
                check("UPDATE own record", updated.get("ok") is True, str(updated.get("error", ""))[:140])

                fixtures = content_payload(client.call("buildium_created_fixtures", {}))
                check("fixture tracked", bool(fixtures.get("created")), json.dumps(fixtures.get("created")))

                deleted = content_payload(
                    client.call("buildium_call_endpoint", {
                        "method": "DELETE", "path": f"/v1/rentals/appliances/{new_id}", "confirm": True,
                    })
                )
                check("DELETE own record with confirm", deleted.get("ok") is True, str(deleted.get("error", ""))[:140])

                gone = content_payload(
                    client.call("buildium_call_endpoint", {"method": "GET", "path": f"/v1/rentals/appliances/{new_id}"})
                )
                check("record is gone after delete", gone.get("ok") is False and gone.get("status") == 404,
                      f"status={gone.get('status')}")

        # -- additions covering the session-2 surface ----------------------

        print("\n== deployment mode reported over the wire ==")
        health = content_payload(client.call("buildium_health", {}))
        check("health names a deployment mode",
              health.get("deployment_mode") == "sandbox",
              f"deployment_mode={health.get('deployment_mode')}")
        check("health reports whether writes are possible",
              health.get("writes_allowed") is True,
              f"writes_allowed={health.get('writes_allowed')}")
        check("the two file tools are exposed",
              {"buildium_upload_file", "buildium_download_file"} <= set(names),
              f"tools: {sorted(names)}")

        print("\n== auto-pagination ==")
        one_page = content_payload(
            client.call("buildium_list_gl_accounts", {"limit": 10})
        )
        every_page = content_payload(
            client.call("buildium_list_gl_accounts", {"limit": 10, "all_pages": True})
        )
        check("all_pages returns more than one page holds",
              every_page.get("count", 0) > one_page.get("count", 0),
              f"one page={one_page.get('count')}, all={every_page.get('count')}")
        check("a complete auto-paginated result says so",
              every_page.get("complete") is True and every_page.get("pages_followed") is True,
              json.dumps({k: every_page.get(k) for k in ("complete", "pages_followed")}))
        check("all_pages is refused on a write",
              content_payload(client.call("buildium_call_endpoint", {
                  "method": "POST", "path": "/v1/rentals/appliances",
                  "all_pages": True, "body": {"Name": "ZZ-MCPTEST-x"},
              })).get("ok") is False,
              "a POST with all_pages should be rejected before it is sent")

        print("\n== describe_endpoint exposes required body fields ==")
        described = content_payload(client.call("buildium_describe_endpoint", {
            "method": "POST", "path": "/v1/rentals/appliances"}))
        body_schema = (described.get("requestBody") or {}).get("schema") or {}
        check("POST body reports its required fields",
              body_schema.get("required") == ["Name", "PropertyId"],
              f"required={body_schema.get('required')}")
        check("deprecation is surfaced structurally",
              described.get("deprecated") is True
              and "2026-10-19" in str(described.get("deprecation_notice")),
              f"deprecated={described.get('deprecated')}")

        print("\n== file round trip through the two-step signed-URL flow ==")
        if property_id is None:
            failures.append("file round trip aborted — no property available")
        else:
            import tempfile as _tf, time as _t
            stamp = int(_t.time())
            payload = f"ZZ-MCPTEST- stdio round trip {stamp}\n".encode() + bytes(range(256))
            with _tf.TemporaryDirectory() as tmp:
                src = Path(tmp) / f"ZZ-MCPTEST-stdio-{stamp}.txt"
                src.write_bytes(payload)
                categories = content_payload(
                    client.call("buildium_call_endpoint",
                                {"method": "GET", "path": "/v1/files/categories",
                                 "query": {"limit": 1}})
                )
                cat_id = ((categories.get("data") or [{}])[0] or {}).get("Id")
                uploaded = content_payload(client.call("buildium_upload_file", {
                    "file_path": str(src), "title": f"ZZ-MCPTEST-stdio-{stamp}",
                    "category_id": cat_id, "entity_type": "Rental",
                    "entity_id": property_id,
                }))
                check("upload completes both steps",
                      uploaded.get("ok") is True
                      and uploaded.get("bytes_sent") == len(payload),
                      str(uploaded.get("error", ""))[:160])

                file_id = None
                if uploaded.get("ok"):
                    # Buildium finalizes the file record asynchronously, on
                    # its own schedule: sandbox latency measured 2-5s on most
                    # runs and 227-270s on three consecutive runs. Polling for
                    # minutes is not worth it in a smoke test, so this polls
                    # briefly and then *warns* rather than fails — the upload
                    # itself was already proven by the storage host's 2xx.
                    import time as _time2
                    for _ in range(UPLOAD_POLL_ATTEMPTS):
                        _time2.sleep(UPLOAD_POLL_INTERVAL_S)
                        listing = content_payload(client.call(
                            "buildium_call_endpoint",
                            {"method": "GET", "path": "/v1/files",
                             "query": {"limit": 100}}))
                        hits = [f for f in (listing.get("data") or [])
                                if f.get("Title") == f"ZZ-MCPTEST-stdio-{stamp}"]
                        if hits:
                            file_id = hits[-1]["Id"]
                            break
                polled = UPLOAD_POLL_ATTEMPTS * UPLOAD_POLL_INTERVAL_S
                warn("uploaded file appears as a record", file_id is not None,
                     f"file_id={file_id} (Buildium finalizes uploads asynchronously; "
                     f"polled for {polled}s — latency of several minutes has been "
                     "observed, in which case the download checks below are skipped)")

                if file_id:
                    dest = client.download_dir / "roundtrip.bin"
                    downloaded = content_payload(client.call("buildium_download_file", {
                        "file_id": file_id, "save_to": "roundtrip.bin"}))
                    check("download completes both steps",
                          downloaded.get("ok") is True,
                          str(downloaded.get("error", ""))[:160])
                    check("downloaded bytes are identical to what was uploaded",
                          dest.is_file() and dest.read_bytes() == payload,
                          f"{dest.stat().st_size if dest.is_file() else 0} bytes vs {len(payload)}")

        print("\n" + "=" * 60)
        if failures:
            print(f"FAILURES ({len(failures)}): " + "; ".join(failures))
        else:
            print("ALL CHECKS PASSED")
        return 1 if failures else 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
