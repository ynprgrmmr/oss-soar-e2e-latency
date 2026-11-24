#!/usr/bin/env python3
"""Create (or replace) Shuffle workflow e2e-block-src + its webhook via the API.

Run ON the soar VM (talks to the backend at 127.0.0.1:5001). Secrets come
from the environment only and are stored as Shuffle workflow variables:

  SHUFFLE_API_KEY, MIKROTIK_URL, MIKROTIK_USER, MIKROTIK_PASSWORD,
  MIKROTIK_CA_FILE, BLOCK_TIMEOUT (default 60s)

Prints the webhook path for Wazuh's <integration><hook_url>.

  --variant single    (default) e2e-block-src: one execute_python action that
                      stamps T1_soar/T2 and calls CHR (TLS verified with the CA)
  --variant two-step  e2e-block-src-2step (condition C3): execute_python stamps
                      T1_soar, then the stock HTTP app PUTs to CHR. T2 comes from
                      Shuffle's millisecond result timestamps, and the HTTP app
                      cannot pin a CA, so TLS verification is off for that call.
"""
import argparse, json, os, sys, uuid, urllib.request
from pathlib import Path

BASE = os.environ.get("SHUFFLE_BACKEND", "http://127.0.0.1:5001")
NAMES = {"single": "e2e-block-src", "two-step": "e2e-block-src-2step"}
HERE = Path(__file__).resolve().parent


def call(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + os.environ["SHUFFLE_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:500]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(NAMES), default="single")
    args = ap.parse_args()
    NAME = NAMES[args.variant]

    s, apps = call("/api/v1/apps")
    tools = next(a for a in apps if a["name"] == "Shuffle Tools" and a["app_version"] == "1.2.0")
    http = next(a for a in apps if a["name"].lower() == "http" and a["app_version"] == "1.4.0")

    # Replace an existing workflow of the same name (keeps reruns idempotent).
    s, wfs = call("/api/v1/workflows")
    for w in wfs if isinstance(wfs, list) else []:
        if w.get("name") == NAME:
            for t in w.get("triggers") or []:
                call(f"/api/v1/hooks/{t['id']}/delete")
            call(f"/api/v1/workflows/{w['id']}", method="DELETE")

    s, wf = call("/api/v1/workflows", {"name": NAME, "description": "soar-net-lab 01: Wazuh rule 100510 -> CHR address-list"})
    assert s == 200, (s, wf)
    wf_id, action_id, trig_id = wf["id"], str(uuid.uuid4()), str(uuid.uuid4())

    code = (HERE / ("stamp_and_block.py" if args.variant == "single" else "stamp_only.py")).read_text()
    variables = {
        "mikrotik_url": os.environ["MIKROTIK_URL"],
        "mikrotik_user": os.environ["MIKROTIK_USER"],
        "mikrotik_password": os.environ["MIKROTIK_PASSWORD"],
        "mikrotik_ca_pem": Path(os.environ["MIKROTIK_CA_FILE"]).read_text(),
        "block_timeout": os.environ.get("BLOCK_TIMEOUT", "60s"),
    }
    wf.update({
        "start": action_id,
        "actions": [{
            "id": action_id, "app_name": "Shuffle Tools", "app_version": "1.2.0", "app_id": tools["id"],
            "name": "execute_python", "label": "stamp_and_block", "environment": "Shuffle",
            "is_start_node": True, "position": {"x": 400, "y": 200},
            "parameters": [{"name": "code", "value": code, "required": True, "multiline": True}],
        }],
        "triggers": [{
            "id": trig_id, "app_name": "Webhook", "app_version": "1.0.0", "name": "Webhook",
            "label": "wazuh_in", "trigger_type": "WEBHOOK", "status": "uninitialized",
            "environment": "Shuffle", "position": {"x": 100, "y": 200},
            "parameters": [{"name": "url", "value": f"{BASE}/api/v1/hooks/webhook_{trig_id}"},
                           {"name": "tmp", "value": ""}, {"name": "auth_headers", "value": ""}],
        }],
        "branches": [{"id": str(uuid.uuid4()), "source_id": trig_id, "destination_id": action_id}],
        "workflow_variables": [{"id": str(uuid.uuid4()), "name": k, "value": v} for k, v in variables.items()],
        "execution_environment": "Shuffle",
    })
    if args.variant == "two-step":
        wf["actions"][0]["label"] = "stamp"
        put_id = str(uuid.uuid4())
        wf["actions"].append({
            "id": put_id, "app_name": "http", "app_version": "1.4.0", "app_id": http["id"],
            "name": "PUT", "label": "chr_put", "environment": "Shuffle", "position": {"x": 700, "y": 200},
            "parameters": [
                {"name": "url", "value": "$mikrotik_url/rest/ip/firewall/address-list", "required": True},
                {"name": "body", "value": json.dumps({"list": "soar-blocklist", "address": "$stamp.message.srcip",
                                                      "timeout": "$block_timeout", "comment": "run=$stamp.message.run_id"})},
                {"name": "headers", "value": "Content-Type: application/json"},
                {"name": "username", "value": "$mikrotik_user"},
                {"name": "password", "value": "$mikrotik_password"},
                {"name": "verify", "value": "false"},
                {"name": "timeout", "value": "5"},
            ],
        })
        wf["branches"].append({"id": str(uuid.uuid4()), "source_id": action_id, "destination_id": put_id})

    s, r = call(f"/api/v1/workflows/{wf_id}", wf, method="PUT")
    assert s == 200, ("save workflow", s, r)

    s, r = call("/api/v1/hooks/new", {"name": "wazuh_in", "type": "webhook", "id": trig_id, "workflow": wf_id,
                                      "start": action_id, "environment": "Shuffle", "auth": "",
                                      "custom_response": "", "version": "v1"})
    assert s == 200, ("start webhook", s, r)

    print(json.dumps({"variant": args.variant, "workflow_id": wf_id, "webhook_path": f"/api/v1/hooks/webhook_{trig_id}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
