#!/usr/bin/env python3
"""Aggregate raw/*/trial.json into per-trial segments and per-condition stats.

    python3 summarize.py            # writes results/trials.csv, results/stats.csv
                                    # and prints a Markdown table
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from trialio import RAW_DIR

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# name -> (end, start)
SEGMENTS = {
    "d_detect_ms": ("t1_detect_ns", "t0_ns"),
    "d_dispatch_ms": ("t1_soar_ns", "t1_detect_ns"),
    "d_api_ms": ("t2_ns", "t1_soar_ns"),
    "d_enforce_ms": ("t3_ns", "t2_ns"),
    "d_e2e_ms": ("t3_ns", "t0_ns"),
}


def seg(trial: dict, end: str, start: str) -> float | None:
    a, b = trial.get(end), trial.get(start)
    return round((a - b) / 1e6, 3) if a is not None and b is not None else None


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear interpolation (same as numpy default)."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def stats(vals: list[float]) -> dict:
    v = sorted(vals)
    return {
        "n": len(v),
        "min": round(v[0], 3),
        "mean": round(statistics.fmean(v), 3),
        "p50": round(percentile(v, 0.50), 3),
        "p90": round(percentile(v, 0.90), 3),
        "p95": round(percentile(v, 0.95), 3),
        "max": round(v[-1], 3),
        "stdev": round(statistics.stdev(v), 3) if len(v) > 1 else 0.0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    p.add_argument("--phase-period-s", type=float, default=2.0,
                   help="period of the loop to test phase-locking against (Wazuh logcollector: 2 s)")
    args = p.parse_args()

    trials = [json.loads(f.read_text()) for f in sorted(args.raw_dir.glob("*/trial.json"))]
    if not trials:
        print("no trials found", file=sys.stderr)
        return 1

    rows = []
    for t in trials:
        row = {"run_id": t["run_id"], "condition": t.get("condition"), "blocked": t.get("blocked")}
        for name, (end, start) in SEGMENTS.items():
            row[name] = seg(t, end, start)
        row["t3_uncertainty_ms"] = round(t.get("probe_interval_ns", 0) / 1e6, 3)
        rows.append(row)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    with open(args.results_dir / "trials.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    by_cond: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    missing: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if not r["blocked"]:
            continue
        for name in SEGMENTS:
            if r[name] is not None:
                by_cond[r["condition"]][name].append(r[name])
            else:
                missing[r["condition"]][name] += 1

    stat_rows = []
    for cond in sorted(by_cond):
        for name in SEGMENTS:
            vals = by_cond[cond][name]
            if vals:
                stat_rows.append({"condition": cond, "segment": name, **stats(vals),
                                  "missing": missing[cond][name]})

    if stat_rows:
        with open(args.results_dir / "stats.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(stat_rows[0]))
            w.writeheader()
            w.writerows(stat_rows)

        cols = ["condition", "segment", "n", "missing", "min", "p50", "mean", "p90", "p95", "max", "stdev"]
        print("| " + " | ".join(cols) + " |")
        print("|" + "---|" * len(cols))
        for s in stat_rows:
            print("| " + " | ".join(str(s[c]) for c in cols) + " |")

    # Phase concentration of T0 against a periodic loop on the path. R near 0
    # means trial starts are spread over the loop (unbiased D_detect); R near
    # 1 means they are phase-locked. For uniform phases E[R] ~ sqrt(pi/(4n)).
    t0_by_cond: dict[str, list[int]] = defaultdict(list)
    for t in trials:
        if t.get("blocked") and t.get("t0_ns"):
            t0_by_cond[t.get("condition")].append(t["t0_ns"])
    phase_rows = []
    for cond in sorted(t0_by_cond):
        ang = [2 * math.pi * ((ns / 1e9) % args.phase_period_s) / args.phase_period_s for ns in t0_by_cond[cond]]
        r = math.hypot(sum(map(math.cos, ang)), sum(map(math.sin, ang))) / len(ang)
        n = len(ang)
        z = n * r * r  # Rayleigh test of uniformity (Zar 2010, eq. 27.4 approximation)
        p_val = math.exp(math.sqrt(1 + 4 * n + 4 * (n * n - z * n)) - (1 + 2 * n)) if n > 1 else 1.0
        phase_rows.append({"condition": cond, "n": n, "period_s": args.phase_period_s,
                           "phase_R": round(r, 3), "uniform_expected_R": round(math.sqrt(math.pi / (4 * n)), 3),
                           "rayleigh_p": float(f"{p_val:.3g}")})
    if phase_rows:
        with open(args.results_dir / "phase.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(phase_rows[0]))
            w.writeheader()
            w.writerows(phase_rows)
        print("\n| condition | n | phase R (%.0f s) | uniform E[R] | Rayleigh p |" % args.phase_period_s)
        print("|---|---|---|---|---|")
        for pr in phase_rows:
            print(f"| {pr['condition']} | {pr['n']} | {pr['phase_R']} | {pr['uniform_expected_R']} | {pr['rayleigh_p']} |")

    failed = sum(1 for r in rows if not r["blocked"])
    print(f"\ntrials={len(rows)} blocked={len(rows) - failed} not_blocked={failed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
