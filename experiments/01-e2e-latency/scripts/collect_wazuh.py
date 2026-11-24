#!/usr/bin/env python3
"""Extract T1_detect from Wazuh alerts.json and merge into trial.json files.

alerts.json is JSON-lines at /var/ossec/logs/alerts/alerts.json on the manager.
Copy it (or a filtered slice) next to this repo first, e.g.:

    ssh soar 'sudo grep "\"id\":\"100510\"" /var/ossec/logs/alerts/alerts.json' > /tmp/alerts-100510.json
    python3 collect_wazuh.py /tmp/alerts-100510.json

Only rule 100510 alerts are read; nothing else from the manager is kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trialio import RAW_DIR, find_run_id, iso_to_ns, merge

RULE_ID = "100510"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("alerts", type=Path)
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = p.parse_args()

    merged = skipped = 0
    with args.alerts.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alert = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(alert.get("rule", {}).get("id")) != RULE_ID:
                continue
            run_id = find_run_id(alert.get("full_log", ""))
            if not run_id:
                skipped += 1
                continue
            fields = {
                "t1_detect_ns": iso_to_ns(alert["timestamp"]),
                "wazuh_alert_id": alert.get("id"),
                "wazuh_agent": alert.get("agent", {}).get("name"),
            }
            if merge(args.raw_dir, run_id, fields, "wazuh"):
                merged += 1
            else:
                skipped += 1
    print(json.dumps({"merged": merged, "skipped": skipped}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
