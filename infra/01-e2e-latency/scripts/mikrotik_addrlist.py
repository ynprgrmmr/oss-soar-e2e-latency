#!/usr/bin/env python3
"""Dynamic Address-List management for MikroTik RouterOS v7 via REST API.

Stdlib only (runs on the Linux / Control Host, the SOAR VM, or inside a
Shuffle "execute python" action without extra packages).

Every call prints one JSON line including high-resolution wall-clock
timestamps, so the same code doubles as the T2 probe for the experiment:

    t2_req_ns   - just before the HTTP request is sent
    t2_resp_ns  - just after the full HTTP response is read

Configuration via environment (see ../.env.example):
    MIKROTIK_URL        e.g. https://10.10.0.10
    MIKROTIK_USER
    MIKROTIK_PASSWORD
    MIKROTIK_CA_FILE    path to soar-lab-ca.crt (preferred)
    MIKROTIK_INSECURE   "1" to skip TLS verification (lab only)

Examples:
    mikrotik_addrlist.py add    10.10.1.20 --timeout 60s --comment run=abc123
    mikrotik_addrlist.py list
    mikrotik_addrlist.py check  10.10.1.20
    mikrotik_addrlist.py remove 10.10.1.20
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_LIST = "soar-blocklist"
RESOURCE = "/rest/ip/firewall/address-list"


class RouterOSClient:
    def __init__(self, base_url: str, user: str, password: str,
                 ca_file: str | None = None, insecure: bool = False,
                 timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.timeout = timeout
        if insecure:
            self.ctx = ssl._create_unverified_context()  # noqa: S323 - lab only
        else:
            self.ctx = ssl.create_default_context(cafile=ca_file)

    @classmethod
    def from_env(cls) -> "RouterOSClient":
        missing = [k for k in ("MIKROTIK_URL", "MIKROTIK_USER", "MIKROTIK_PASSWORD")
                   if not os.environ.get(k)]
        if missing:
            sys.exit(f"missing env: {', '.join(missing)}")
        return cls(
            os.environ["MIKROTIK_URL"],
            os.environ["MIKROTIK_USER"],
            os.environ["MIKROTIK_PASSWORD"],
            ca_file=os.environ.get("MIKROTIK_CA_FILE") or None,
            insecure=os.environ.get("MIKROTIK_INSECURE") == "1",
        )

    def request(self, method: str, path: str, body: dict | None = None,
                query: dict | None = None) -> dict:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)

        t_req = time.time_ns()
        m_req = time.monotonic_ns()
        status, payload, error = None, None, None
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                status = resp.status
                raw = resp.read()
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read()
            error = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raw = b""
            error = str(e)
        m_resp = time.monotonic_ns()
        t_resp = time.time_ns()

        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw.decode(errors="replace")

        return {
            "method": method,
            "path": path,
            "status": status,
            "ok": error is None and status is not None and 200 <= status < 300,
            "error": error,
            "t2_req_ns": t_req,
            "t2_resp_ns": t_resp,
            # monotonic delta is immune to clock steps during the call
            "api_rtt_ms": round((m_resp - m_req) / 1e6, 3),
            "response": payload,
        }

    # -- Address-List operations ------------------------------------------
    def add(self, address: str, list_name: str = DEFAULT_LIST,
            timeout: str | None = None, comment: str | None = None) -> dict:
        body = {"list": list_name, "address": address}
        if timeout:
            body["timeout"] = timeout  # auto-expiry, e.g. "60s" (resets lab between trials)
        if comment:
            body["comment"] = comment
        return self.request("PUT", RESOURCE, body)

    def find(self, address: str | None = None, list_name: str = DEFAULT_LIST) -> dict:
        q = {"list": list_name}
        if address:
            q["address"] = address
        return self.request("GET", RESOURCE, query=q)

    def remove(self, address: str, list_name: str = DEFAULT_LIST) -> dict:
        found = self.find(address, list_name)
        entries = found["response"] if found["ok"] and isinstance(found["response"], list) else []
        if not entries:
            found["ok"] = False
            found["error"] = found["error"] or "not found"
            return found
        # RouterOS rejects a percent-encoded '*' in the id (*1A -> %2A1A gives
        # HTTP 400 "missing or invalid resource identifier"), so keep it literal.
        results = [self.request("DELETE", f"{RESOURCE}/{urllib.parse.quote(e['.id'], safe='*')}")
                   for e in entries]
        last = results[-1]
        last["deleted"] = len(results)
        last["ok"] = all(r["ok"] for r in results)
        return last


def _validate_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_network(value, strict=False)) if "/" in value \
            else str(ipaddress.ip_address(value))
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--list", default=DEFAULT_LIST, dest="list_name")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add address to list")
    a.add_argument("address", type=_validate_ip)
    a.add_argument("--timeout", help='RouterOS duration, e.g. "60s"')
    a.add_argument("--comment")

    r = sub.add_parser("remove", help="remove address from list")
    r.add_argument("address", type=_validate_ip)

    c = sub.add_parser("check", help="is address in list?")
    c.add_argument("address", type=_validate_ip)

    sub.add_parser("list", help="show list entries")

    args = p.parse_args(argv)
    cli = RouterOSClient.from_env()

    if args.cmd == "add":
        res = cli.add(args.address, args.list_name, args.timeout, args.comment)
    elif args.cmd == "remove":
        res = cli.remove(args.address, args.list_name)
    elif args.cmd == "check":
        res = cli.find(args.address, args.list_name)
        res["present"] = bool(res["ok"] and res["response"])
    else:
        res = cli.find(None, args.list_name)

    print(json.dumps(res, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
