#!/usr/bin/env python3
"""Extract T1_soar / T2 from Shuffle executions (or the C4 AR log) into trial.json files.

The workflow's python action prints a JSON line with "soar_lab": true and
t1_soar_ns / t2_req_ns / t2_resp_ns (see infra/01-e2e-latency/shuffle/workflow.md).
This script scans execution results for that line, so it does not depend on
Shuffle's own (second-resolution) metadata.

    # pull via API (env: SHUFFLE_URL, SHUFFLE_API_KEY, SHUFFLE_WORKFLOW_ID)
    python3 collect_shuffle.py --api
    # or from an exported JSON file
    python3 collect_shuffle.py --from-file executions.json

TODO(verify on real Shuffle): endpoint path and the shape of the
execution/result objects. The scan below is deliberately structure-agnostic.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

from trialio import RAW_DIR, merge


def iter_marker_objects(node):
    """Yield every dict carrying soar_lab=true, at any depth, including JSON
    embedded as strings (Shuffle stores action results as strings)."""
    if isinstance(node, dict):
        if node.get("soar_lab") is True:
            yield node
        for v in node.values():
            yield from iter_marker_objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_marker_objects(v)
    elif isinstance(node, str) and "soar_lab" in node:
        for line in node.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    yield from iter_marker_objects(json.loads(line))
                except json.JSONDecodeError:
                    pass
        try:
            yield from iter_marker_objects(json.loads(node))
        except json.JSONDecodeError:
            pass


def fetch_api() -> object:
    base = os.environ["SHUFFLE_URL"].rstrip("/")
    wf = os.environ["SHUFFLE_WORKFLOW_ID"]
    req = urllib.request.Request(
        f"{base}/api/v1/workflows/{wf}/executions",
        headers={"Authorization": f"Bearer {os.environ['SHUFFLE_API_KEY']}"},
    )
    ctx = ssl._create_unverified_context() if os.environ.get("SHUFFLE_INSECURE") == "1" \
        else ssl.create_default_context(cafile=os.environ.get("SHUFFLE_CA_FILE") or None)
    with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
        return json.loads(r.read())


def merge_t2_from_action(data, label: str, raw_dir: Path) -> int:
    """Per execution: T1_soar from the marker JSON (ns), T2 from the result of
    action `label` (Shuffle's started_at/completed_at, ms). The HTTP app does
    not expose its own request timing, so T2 here = action completed_at."""
    execs = data if isinstance(data, list) else (data.get("executions") or [])
    merged = skipped = 0
    for e in execs:
        markers = list(iter_marker_objects(e.get("results") or []))
        res = next((r for r in e.get("results") or [] if (r.get("action") or {}).get("label") == label), None)
        if not markers or res is None or not markers[0].get("run_id"):
            skipped += 1
            continue
        mk = markers[0]
        status = None
        try:
            status = json.loads(res.get("result") or "{}").get("status")
        except (json.JSONDecodeError, AttributeError):
            pass
        fields = {
            "t1_soar_ns": mk.get("t1_soar_ns"),
            "t2_req_ns": int(res["started_at"]) * 1_000_000 if res.get("started_at") else None,
            "t2_ns": int(res["completed_at"]) * 1_000_000 if res.get("completed_at") else None,
            "t2_source": f"shuffle-result-ms:{label}",
            "mikrotik_status": status,
        }
        if merge(raw_dir, mk["run_id"], fields, "shuffle-2step"):
            merged += 1
        else:
            skipped += 1
    print(json.dumps({"merged": merged, "skipped": skipped}))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--api", action="store_true")
    src.add_argument("--from-file", type=Path)
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--t2-action", metavar="LABEL",
                   help="C3: take T2 from this action's Shuffle result timestamps "
                        "(started_at/completed_at, ms resolution) instead of the marker JSON")
    args = p.parse_args()

    if args.api:
        data = fetch_api()
    else:
        text = args.from_file.read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = text  # JSON lines (e.g. the C4 active-response log): scanned line by line

    if args.t2_action:
        return merge_t2_from_action(data, args.t2_action, args.raw_dir)

    merged = skipped = 0
    seen = set()
    for obj in iter_marker_objects(data):
        run_id = obj.get("run_id")
        key = (run_id, obj.get("t2_resp_ns"))
        if not run_id or key in seen:
            continue
        seen.add(key)
        fields = {
            "t1_soar_ns": obj.get("t1_soar_ns"),
            "t2_req_ns": obj.get("t2_req_ns"),
            "t2_ns": obj.get("t2_resp_ns"),
            "mikrotik_status": obj.get("status"),
        }
        if merge(args.raw_dir, run_id, fields, "shuffle"):
            merged += 1
        else:
            skipped += 1
    print(json.dumps({"merged": merged, "skipped": skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
