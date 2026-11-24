#!/usr/bin/env python3
"""Break D_dispatch (T1_detect -> T1_soar) into Wazuh-side and Shuffle-side parts.

Inputs (collected read-only on the soar VM; not committed, they are bulky):
  --backend  docker logs -t shuffle-backend  | grep -E "webhook callback|should execute onprem"
  --worker   docker logs -t <shuffle-workers> | grep -E "Inside Decide|Action: Send|Should run towards port"
  --executions  Shuffle API executions JSON for workflow e2e-block-src
Output: rows appended/replaced in results/dispatch_breakdown.csv (one per run_id)

    python3 breakdown_dispatch.py --condition C1 --backend b.log --worker w.log --executions ex.json
"""
from __future__ import annotations

import argparse, csv, json, re
from datetime import datetime, timezone
from pathlib import Path

from trialio import RAW_DIR

OUT = Path(__file__).resolve().parent.parent / "results" / "dispatch_breakdown.csv"
FIELDS = ["run_id", "condition", "wazuh_alert_to_webhook_ms", "shuffle_webhook_to_created_ms",
          "shuffle_queue_ms", "shuffle_worker_to_app_ms", "shuffle_app_to_code_ms", "dispatch_ms"]


def ns(ts: str) -> int:
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d+)Z", ts)
    sec = int(datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
    return sec * 10**9 + int(m.group(2).ljust(9, "0")[:9])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--condition", required=True)
    p.add_argument("--backend", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True)
    p.add_argument("--executions", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args()

    ex = json.loads(a.executions.read_text()); ex = ex if isinstance(ex, list) else ex.get("executions", [])
    hooks, created, wk = [], {}, {}
    for line in a.backend.read_text().splitlines():
        if "webhook callback" in line:
            hooks.append(ns(line.split()[0]))
        m = re.search(r"\]\[([0-9a-f-]{36})\] Execution: should execute onprem", line)
        if m:
            created.setdefault(m.group(1), ns(line.split()[0]))
    for line in a.worker.read_text().splitlines():
        m = re.search(r"\]\[([0-9a-f-]{36})\] (Inside Decide|Action: Send|Should run towards port)", line)
        if m:
            wk.setdefault(m.group(1), {}).setdefault(m.group(2), ns(line.split()[0]))

    rows = {}
    if a.out.exists():
        rows = {r["run_id"]: r for r in csv.DictReader(a.out.open())}
    added = 0
    for e in ex:
        m = re.search(r"soar-probe-([0-9a-f]{8})", str(e.get("execution_argument")))
        tf = a.raw_dir / (m.group(1) if m else "-") / "trial.json"
        if not m or not tf.exists():
            continue
        t = json.loads(tf.read_text())
        c, w = created.get(e["execution_id"]), wk.get(e["execution_id"], {})
        if t.get("condition") != a.condition or not c or len(w) < 3:
            continue
        hook = max(h for h in hooks if h <= c)
        f = lambda x: f"{x / 1e6:.3f}"
        rows[t["run_id"]] = {
            "run_id": t["run_id"], "condition": a.condition,
            "wazuh_alert_to_webhook_ms": f(hook - t["t1_detect_ns"]),
            "shuffle_webhook_to_created_ms": f(c - hook),
            "shuffle_queue_ms": f(w["Inside Decide"] - c),
            "shuffle_worker_to_app_ms": f(w["Should run towards port"] - w["Inside Decide"]),
            "shuffle_app_to_code_ms": f(t["t1_soar_ns"] - w["Should run towards port"]),
            "dispatch_ms": f(t["t1_soar_ns"] - t["t1_detect_ns"]),
        }
        added += 1
    with a.out.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=FIELDS); wr.writeheader()
        wr.writerows(sorted(rows.values(), key=lambda r: (r["condition"], r["run_id"])))
    print(json.dumps({"condition": a.condition, "rows": added, "out": str(a.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
