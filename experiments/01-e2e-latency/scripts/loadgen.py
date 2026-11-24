#!/usr/bin/env python3
"""Background alert load for condition C5. Runs on the target VM.

Writes sshd-style "Invalid user loadgen-<seq>" lines to syslog (auth) at a
fixed rate. They go through the same journald -> Wazuh agent -> manager path
as the measured event and match rule 5710 (and frequency rules such as 5712),
but NOT rule 100510 (prefix is loadgen-, not soar-probe-), so they never
reach Shuffle or the CHR. The source IP is a documentation address
(192.0.2.99): no network traffic is generated.

    sudo systemd-run --unit soar-loadgen python3 loadgen.py --rate 20
    sudo systemctl stop soar-loadgen
"""
import argparse, os, signal, syslog, time

p = argparse.ArgumentParser()
p.add_argument("--rate", type=float, default=20.0, help="events per second")
p.add_argument("--src", default="192.0.2.99")
p.add_argument("--status-file", default="/run/soar-loadgen.status")
args = p.parse_args()

stop = False
def _stop(*_):
    global stop
    stop = True
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)

syslog.openlog(ident="sshd", logoption=syslog.LOG_PID, facility=syslog.LOG_AUTH)
interval = 1.0 / args.rate
seq, start = 0, time.monotonic()
next_t = start
while not stop:
    syslog.syslog(syslog.LOG_INFO, f"Invalid user loadgen-{seq} from {args.src} port {40000 + seq % 20000}")
    seq += 1
    if seq % int(args.rate * 10) == 0:  # status every ~10 s
        with open(args.status_file, "w") as f:
            f.write(f"{time.time():.0f} sent={seq} rate={seq / (time.monotonic() - start):.2f}\n")
    next_t += interval
    delay = next_t - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    else:
        next_t = time.monotonic()
with open(args.status_file, "w") as f:
    f.write(f"{time.time():.0f} stopped sent={seq}\n")
