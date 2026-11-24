#!/usr/bin/env python3
"""Run one E2E latency trial from the attacker VM. Records T0 and T3.

Flow:
  1. start UDP prober (attacker -> target echo), verify baseline replies
  2. T0 = time.time_ns(); ssh soar-probe-<run_id>@target  (fires Wazuh rule 100510)
  3. wait until replies stop for --block-detect-s (terminal loss run)
  4. T3 = send time of the first probe in the terminal loss run

Output: <out-dir>/<run_id>/probes.csv and trial.json

    python3 run_trial.py --target 10.10.2.20 --condition C1
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

PKT = struct.Struct("!8sQQ")  # magic, seq, send_ns
MAGIC = b"SOARLAB1"


class Prober:
    def __init__(self, target: str, port: int, interval_s: float) -> None:
        self.addr = (target, port)
        self.interval_s = interval_s
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.2)
        self.sent: dict[int, int] = {}
        self.recv: dict[int, int] = {}
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.seq = 0

    def _sender(self) -> None:
        next_t = time.monotonic()
        while not self.stop_evt.is_set():
            now_ns = time.time_ns()
            with self.lock:
                seq = self.seq
                self.sent[seq] = now_ns
                self.seq += 1
            try:
                self.sock.sendto(PKT.pack(MAGIC, seq, now_ns), self.addr)
            except OSError:
                pass  # e.g. transient ENOBUFS; counted as lost
            next_t += self.interval_s
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.monotonic()  # fell behind; don't burst

    def _receiver(self) -> None:
        while not self.stop_evt.is_set():
            try:
                data, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                continue
            t = time.time_ns()
            if len(data) < PKT.size:
                continue
            magic, seq, _ = PKT.unpack(data[:PKT.size])
            if magic == MAGIC:
                with self.lock:
                    self.recv.setdefault(seq, t)

    def start(self) -> None:
        self.threads = [threading.Thread(target=self._sender, daemon=True),
                        threading.Thread(target=self._receiver, daemon=True)]
        for th in self.threads:
            th.start()

    def stop(self) -> None:
        self.stop_evt.set()
        for th in self.threads:
            th.join(timeout=2)

    def last_ok(self) -> int | None:
        with self.lock:
            return max(self.recv) if self.recv else None

    def last_reply_age_s(self) -> float:
        with self.lock:
            if not self.recv:
                return float("inf")
            return (time.time_ns() - self.recv[max(self.recv)]) / 1e9

    def snapshot(self) -> tuple[dict[int, int], dict[int, int]]:
        with self.lock:
            return dict(self.sent), dict(self.recv)


def fire_trigger(target: str, run_id: str, timeout_s: float) -> None:
    """Connect to sshd as an invalid user. No password is ever sent."""
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=3",
           "-o", "PreferredAuthentications=password", "-o", "LogLevel=ERROR",
           f"soar-probe-{run_id}@{target}", "true"]
    try:
        subprocess.run(cmd, timeout=timeout_s, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        pass


def compute_t3(sent: dict[int, int], recv: dict[int, int]) -> dict:
    if not recv:
        return {"t3_ns": None, "last_ok_seq": None}
    last_ok = max(recv)
    first_lost = last_ok + 1
    if first_lost not in sent:
        return {"t3_ns": None, "last_ok_seq": last_ok}
    return {
        "t3_ns": sent[first_lost],
        "t3_lower_ns": sent[last_ok],  # true cut lies in (lower, t3]
        "last_ok_seq": last_ok,
        "terminal_loss_count": max(sent) - last_ok,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--target", required=True)
    p.add_argument("--port", type=int, default=9999)
    p.add_argument("--interval-ms", type=float, default=10.0)
    p.add_argument("--baseline-s", type=float, default=3.0)
    p.add_argument("--block-detect-s", type=float, default=2.0)
    p.add_argument("--post-block-s", type=float, default=1.0)
    p.add_argument("--timeout-s", type=float, default=120.0)
    p.add_argument("--condition", default="C1")
    p.add_argument("--run-id", default=None)
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent.parent / "raw"))
    args = p.parse_args()

    run_id = args.run_id or secrets.token_hex(4)
    if not re.fullmatch(r"[0-9a-f]{8}", run_id):
        p.error("--run-id must be 8 lowercase hex chars (matched by collectors)")
    out = Path(args.out_dir) / run_id
    out.mkdir(parents=True, exist_ok=False)

    prober = Prober(args.target, args.port, args.interval_ms / 1000)
    prober.start()
    time.sleep(args.baseline_s)
    if prober.last_reply_age_s() > 0.5:
        prober.stop()
        print(json.dumps({"run_id": run_id, "error": "no baseline replies (still blocked?)"}))
        return 2

    t0_ns = time.time_ns()
    trig = threading.Thread(target=fire_trigger, args=(args.target, run_id, 10.0), daemon=True)
    trig.start()

    blocked = False
    deadline = time.monotonic() + args.timeout_s
    while time.monotonic() < deadline:
        if prober.last_reply_age_s() >= args.block_detect_s:
            blocked = True
            break
        time.sleep(0.05)
    if blocked:
        time.sleep(args.post_block_s)
    prober.stop()

    sent, recv = prober.snapshot()
    t3 = compute_t3(sent, recv) if blocked else {"t3_ns": None}

    with open(out / "probes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "send_ns", "recv_ns", "rtt_us"])
        for seq in sorted(sent):
            r = recv.get(seq)
            w.writerow([seq, sent[seq], r if r else "",
                        round((r - sent[seq]) / 1e3, 1) if r else ""])

    baseline_rtts = [(recv[s] - sent[s]) / 1e3 for s in recv if sent[s] < t0_ns]
    trial = {
        "run_id": run_id,
        "condition": args.condition,
        "attacker_host": socket.gethostname(),
        "target": args.target,
        "params": {k: v for k, v in vars(args).items() if k not in ("run_id", "out_dir")},
        "blocked": blocked,
        "t0_ns": t0_ns,
        **t3,
        "probe_interval_ns": int(args.interval_ms * 1e6),
        "probes_sent": len(sent),
        "probes_recv": len(recv),
        "baseline_rtt_us_median": sorted(baseline_rtts)[len(baseline_rtts) // 2] if baseline_rtts else None,
    }
    (out / "trial.json").write_text(json.dumps(trial, indent=2))
    e2e = (trial["t3_ns"] - t0_ns) / 1e6 if trial.get("t3_ns") else None
    print(json.dumps({"run_id": run_id, "blocked": blocked, "e2e_ms": e2e}))
    return 0 if blocked else 1


if __name__ == "__main__":
    sys.exit(main())
