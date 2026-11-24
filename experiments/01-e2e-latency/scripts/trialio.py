"""Shared helpers: locate trial.json files and merge collected timestamps."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "raw"
RUN_ID_RE = re.compile(r"soar-probe-([0-9a-fA-F]{8})")


def find_run_id(obj) -> str | None:
    text = obj if isinstance(obj, str) else json.dumps(obj)
    m = RUN_ID_RE.search(text)
    return m.group(1) if m else None


def merge(raw_dir: Path, run_id: str, fields: dict, source: str) -> bool:
    """Merge fields into raw/<run_id>/trial.json. Keeps the EARLIEST value if
    a field is reported more than once (e.g. duplicate alerts)."""
    path = raw_dir / run_id / "trial.json"
    if not path.exists():
        return False
    trial = json.loads(path.read_text())
    for k, v in fields.items():
        if v is None:
            continue
        if k.endswith("_ns") and trial.get(k) is not None:
            trial[k] = min(trial[k], v)
        else:
            trial[k] = v
    trial.setdefault("sources", [])
    if source not in trial["sources"]:
        trial["sources"].append(source)
    path.write_text(json.dumps(trial, indent=2))
    return True


def iso_to_ns(ts: str) -> int:
    """Parse Wazuh-style timestamps, e.g. 2026-11-23T05:00:00.123+0000."""
    return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp() * 1e9)
