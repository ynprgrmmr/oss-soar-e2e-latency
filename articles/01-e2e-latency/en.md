---
title: "From Alert to Dropped Packet: Measuring End-to-End Response Latency of OSS SOAR (Wazuh + Shuffle) with a Programmable Router (MikroTik CHR) on OCI"
status: draft (full text, first draft; mirrors ja.md)
lang: en
counterpart: ja.md
---

# From Alert to Dropped Packet — How Fast Does an OSS SOAR Really Block an Attacker?

> Measured on 2026-11-24, 30 tests per condition. Every number in this article can be reproduced from the summaries in
> `experiments/01-e2e-latency/results/` and the raw data in `raw/` of the repository.
> (A "test" is one end-to-end measurement; the scripts and data files call it a *trial*.)

## Summary

- On OCI Always Free, we measured the time from an attack event to the moment the attacker's packets **actually stop**,
  in 5 conditions × 30 tests
- Baseline (Wazuh → Shuffle → MikroTik REST API): **median 5.3 s, p95 7.8 s**
- **About 70% of that is the SOAR hand-off** (Wazuh passing the alert to Shuffle, and Shuffle starting its first action);
  the router side (API call plus the block taking effect) adds up to only about 0.12 s
- Bypassing the SOAR and having Wazuh Active Response call the router directly: **median 1.7 s**. All 30 tests were faster
  than the fastest test through the SOAR
- Each additional Shuffle action adds about 1.1 s of waiting. Dropping in raw vs. filter made no difference.
  Twenty unrelated alerts per second did not slow things down — it got faster
- Along the way we found that test start times had locked onto the Wazuh agent's 2-second cycle ("phase-locking")
  and removed the bias with a random wait

## 1. Why "time to block"?

SOAR (Security Orchestration, Automation and Response) write-ups usually stop at "the alert came in and the workflow ran".
What a defender actually needs to know is **how many seconds pass between noticing the attack and the attacker's traffic
really stopping**. Even when the workflow succeeds, the attacker keeps communicating until the block takes effect in the network.

A router controlled through a REST API (a programmable network, in other words) lets the SOAR drive the enforcement point
directly. We combined the OSS SIEM/XDR Wazuh, the OSS SOAR Shuffle and the software router MikroTik Cloud Hosted Router (CHR),
and measured, segment by segment, the path from the attack event to the moment real packets stop.

## 2. Setup

> Figure: deployment on OCI (Mermaid in [`diagrams.md`](diagrams.md) §1, draw.io in [`diagrams/oci-topology.drawio`](diagrams/oci-topology.drawio))

| VM | Shape | Role |
|---|---|---|
| soar | A1.Flex 3 OCPU / 18 GB (arm64) | Wazuh 4.14.10 (manager, indexer, dashboard) and Shuffle 2.3.0 on the same VM |
| chr | A1.Flex 1 OCPU / 6 GB (arm64) | MikroTik CHR 7.25.1, the enforcement point |
| attacker | E2.1.Micro | Generates the attack event and measures (T0, T3) |
| target | E2.1.Micro | Victim: sshd, Wazuh agent, UDP echo |

Everything runs in OCI us-phoenix-1 (the tenancy's home region) within the Always Free limits.

**All target traffic goes through the router.** The VCN has three subnets — public (soar, CHR WAN side), attacker,
and protected (target, private) — and intra-VCN routing builds these paths:

- traffic from the attacker and public subnets to protected → CHR's WAN-side IP
- traffic leaving the protected subnet (including to other subnets in the VCN) → CHR's LAN-side IP

Return traffic is also steered to CHR with longer prefixes, so the path is symmetric. Source/destination checks are disabled on
both CHR VNICs. With this in place, putting the attacker's IP into the CHR address list `soar-blocklist` is enough to stop
traffic from that IP. The drop happens in `raw/prerouting` (only C2 uses `filter/forward`).

## 3. What we measured and how

> Figure: T0–T3 measurement flow (Mermaid in [`diagrams.md`](diagrams.md) §2, draw.io in [`diagrams/e2e-sequence.drawio`](diagrams/e2e-sequence.drawio))

| Time | Meaning | Taken on |
|---|---|---|
| T0 | Attack event (the attacker opens SSH as the non-existent user `soar-probe-<run_id>`) | attacker |
| T1_detect | Wazuh raises the alert (custom rule 100510) | soar (`alerts.json`) |
| T1_soar | The responder's code starts (a Shuffle action; in C4 the Active Response script) | soar |
| T2 | The router's REST API responds | soar |
| T3 | Packets stop | attacker |

Segment names:

| Segment | Definition |
|---|---|
| Detect | T1_detect − T0 |
| Dispatch | T1_soar − T1_detect |
| API | T2 − T1_soar |
| Enforce | T3 − T2 |
| **E2E** | **T3 − T0** |

**How T3 is defined.** The attacker sends a UDP probe to the target every 10 ms and the target echoes it back.
Once blocked, replies stop; T3 is the send time of the first probe in the final run of unanswered probes. Resolution ±10 ms.

**Clock offsets.** T0 and T3 come from the same attacker clock, so the headline E2E has no cross-host clock error.
Segment values span hosts, so every VM is synced to OCI NTP with chrony. Offsets recorded before and after the tests were
10–150 µs — negligible next to the segments (tens of ms to seconds).

**The responder code.** The Shuffle workflow does everything in one Python action: record T1_soar → PUT to the CHR
address list → record T2. Splitting it into several actions would mix inter-action waiting into the measurement
(how much it mixes in is what C3 measures). TLS to CHR is verified against a CA created for the lab.

## 4. Test conditions

| ID | Condition |
|---|---|
| C1 | Baseline: Wazuh → Shuffle (one Python action) → CHR, raw drop |
| C2 | C1 with the drop moved to filter/forward (no rule accepting established connections) |
| C3 | C1 with Shuffle split into two actions (Python records → stock HTTP app PUTs) |
| C4 | No Shuffle: Wazuh Active Response (running on the manager) calls CHR directly |
| C5 | C1 plus 20 unrelated alerts per second that do not match rule 100510 |

Thirty tests per condition. Before each test we waited for the previous block to expire (60 s) and traffic to come back.

### Pitfall: phase-locking

The first time we measured C4, detection time lined up neatly at about 2 s — although detection follows the same path as C1,
where it varied widely.

The cause was the target's Wazuh agent reading journald **every 2 seconds** (`logcollector.loop_timeout=2`).
C4 tests are short, so tests started at an almost fixed interval and kept landing at the same point of this 2-second cycle —
every time the worst case, with the event happening just after a read.

![Phase of test start times](figures/fig4-phase.svg)

| Run | Phase concentration R | Rayleigh test p | Verdict |
|---|---|---|---|
| First C4 run (fixed interval) | 0.86 | 3.4 × 10⁻¹³ | Locked to the 2 s cycle |
| C4 re-run (0–4 s random wait) | 0.11 | 0.71 | Consistent with uniform |

R measures how concentrated the test starts are when placed on a circle by their position within the 2-second cycle:
0 is uniform, 1 is fully locked. A 0–4 s random wait before each test removed the bias. C2, C3 and C5 were also run with the
random wait (R = 0.05–0.14). C1 ran without it, but showed no bias to begin with (R = 0.24, p = 0.19), so we kept it.
**If the pipeline contains periodic processing, test start times must be randomized.**

## 5. Results

### 5.1 E2E

![CDF of E2E latency](figures/fig2-e2e-cdf.svg)

| Condition | min | median | mean | p95 | max |
|---|---|---|---|---|---|
| C1 baseline | 3,683 | 5,302 | 5,391 | 7,754 | 8,714 |
| C2 filter drop | 3,035 | 5,057 | 5,029 | 6,384 | 6,715 |
| C3 two actions | 3,470 | 6,542 | 6,360 | 8,401 | 8,952 |
| C4 Active Response | 490 | **1,662** | 1,611 | 2,421 | 3,088 |
| C5 background 20 alerts/s | 1,766 | 4,643 | 4,646 | 5,998 | 6,330 |

(ms, n = 30 each, no missing data. C4 is the re-run with the random wait.)

All 150 tests blocked successfully, not one of the five timestamps was missing, and CHR answered HTTP 201 every time.

### 5.2 By segment

![Mean time per segment](figures/fig1-segments.svg)

| Condition | Detect | Dispatch | API | Enforce |
|---|---|---|---|---|
| C1 | 929 | 3,813 | 22 | 102 |
| C2 | 1,315 | 3,562 | 20 | 105 |
| C3 | 1,363 | 3,720 | 1,208* | 102 |
| C4 | 1,467 | 54 | 24 | 105 |
| C5 | 1,098 | 3,219 | 20 | 103 |

(Medians, ms. \* C3's API segment includes the wait until the second action starts.)

Figure 1 stacks the means. Means add up, so each bar's length is the mean E2E; medians do not add up to the E2E median.

## 6. Discussion

### 6.1 The bottleneck is the SOAR hand-off

In the baseline, dispatch is about 75% of E2E. To see where the time goes we read Wazuh's alert timestamps and the Shuffle
backend and worker logs (which carry ns timestamps) — read-only, without changing any settings.

| Breakdown (C1) | Median | Mean |
|---|---|---|
| Wazuh side: alert → Shuffle receives the webhook | 1,874 ms | 1,859 ms |
| Shuffle: webhook → execution created | 66 ms | 180 ms |
| Shuffle: execution created → a worker picks it up | 664 ms | 837 ms |
| Shuffle: worker → hands it to the app container | 742 ms | 769 ms |
| Shuffle: app container → code starts | 339 ms | 366 ms |

The ~1.9 s on the Wazuh side is mostly explained by two things:

- **Waiting for integratord to pick up the alert (0 to ~2 s, median ~0.8 s).** The gap between the time embedded in the
  temporary file name and the alert time was spread evenly over 0–2 s. This is consistent with `alerts.json` being read at
  a fixed interval
- **Starting the integration script (~0.6 s).** Just starting Wazuh's bundled Python and importing `requests` takes 0.6 s
  (measured on soar)

Most of the ~2.2 s on the Shuffle side is waiting for a worker to pick the execution from the queue and waiting for the worker
to hand it to the app container; both range from tens of ms to nearly 2 s. We think these are waits for processes that poll
the queue periodically.

### 6.2 Without the SOAR: 1.7 s

In C4 (Active Response straight to CHR), dispatch shrank to **54 ms (±2 ms)**. Time after detection (T3 − T1_detect) was
184 ms versus 3,937 ms in C1 — about one twenty-first. The E2E distributions separate completely: even the slowest C4 test
(3,088 ms) was faster than the fastest C1 test (3,683 ms) (Mann-Whitney U = 900, p = 2.9 × 10⁻¹¹).

Most of C4's E2E is detection time, set by the agent's 2-second read cycle. Detection did not differ from C1 (p = 0.19),
as expected since the path is the same.

We wrote C4's Active Response script for the OS python3 with the standard library only, not Wazuh's bundled Python:
the bundled interpreter alone takes 0.6 s to start, which would blur the "with vs. without a SOAR layer" comparison.

### 6.3 One more action costs about 1 s

C3's E2E was 1.24 s longer at the median (p = 0.004). Shuffle's own records show that almost all of the increase is
**the wait between the first action finishing and the second one starting (median 1,141 ms)**; the HTTP app's call to CHR
itself took about 52 ms. This is the same kind of wait as "worker → app container" in 6.1, so in Shuffle each additional
action seems to add about a second of waiting.

In C3, T2 is taken from the completion time Shuffle records for the HTTP action (ms resolution). The stock HTTP app cannot
be given a CA, so TLS verification to CHR is off. Enforce (T3 − T2) was about 102 ms, the same as C1, so we believe this
substitution does not introduce a large error.

### 6.4 raw vs filter: no difference — and ~100 ms everywhere

With C2 (filter/forward drop), enforce did not change from C1 (raw): medians 102 ms and 105 ms, p = 0.098. Because this setup
has no "accept established" rule in filter, UDP probes that are already flowing are also dropped in the forward chain.
Whether the drop happens before or after connection tracking does not affect speed here.

On the other hand, the ~100 ms from API response to packets actually stopping was **almost constant at 102–105 ms in all of
C1–C5** (±3–4 ms). We estimate it is the part common to raw and filter — a fixed delay before an address-list change takes
effect in packet processing (unverified).

In production, filter usually starts with an "accept established" rule. In that case a filter drop cannot cut existing
connections. The C2 numbers here assume that rule is absent.

### 6.5 Background alerts make it faster

In C5 we streamed 20 unrelated alerts per second (light compared with the agent's send limit of 500 per second).
E2E did not slow down; the median got 0.66 s shorter (p = 0.018).

![Dispatch breakdown, C1 vs C5](figures/fig3-dispatch-breakdown.svg)

The breakdown shows that **only the Wazuh side (alert → webhook)** got shorter, from a mean of 1,859 ms to 1,227 ms;
the Shuffle side barely changed. We think that when alerts keep arriving, integratord never waits for a new one.
The reduction roughly matches the pick-up wait seen in 6.1 (median ~0.8 s). This load is nowhere near saturation, so the
right reading is "background alerts at this level do not make latency worse".

## 7. Practical takeaways

- **If a few seconds matter, put the block in Active Response.** If it goes through the SOAR, do everything up to the block
  in a single action
- **The Wazuh → SOAR hand-off has about two seconds of waiting.** The integration script's start-up time and integratord's
  wait leave room for improvement through configuration or implementation
- **On RouterOS, drop in raw, or do not accept established connections before the drop.** Otherwise existing connections survive
- **When measuring latency, randomize test start times.** Lining up with periodic processing on the path biases results heavily

## 8. What tripped us up while building it

- **Terraform dependency cycle.** Route tables reference the OCID of CHR's private IP, so we created the subnets first,
  then CHR, then swapped the route tables in
- **CHR custom image.** It had to be converted to QCOW2, with settings for UEFI boot and for use on A1.Flex. The second NIC
  only showed up after one reboot
- **RouterOS defaults.** admin has no password. `place-before=0` fails when the filter list is empty. URL-encoding the `*` in
  a REST API `.id` returns 400. The free license is capped at 1 Mbit/s (irrelevant for the measurement probes)
- **Ubuntu's firewall on OCI.** Host iptables rejects everything except SSH. Ports published by Docker bypass that INPUT rule,
  so we restricted them in DOCKER-USER. On A1 the NIC is `enp0s6`; we first hard-coded `ens3` and the rule never matched
- **Docker 29 and Shuffle.** With Docker 29's default containerd image store, Shuffle could not load its app images.
  Disabling the containerd snapshotter fixed it
- **Wazuh and Shuffle on one VM.** Both use OpenSearch and collide on port 9200. We stopped publishing Shuffle's OpenSearch on the host

## 9. Cost and operations

- Always Free: A1 4 OCPU / 24 GB in total, two E2.1.Micro, 200 GB of boot volumes in total. We deleted one unused VM left over
  from earlier (47 GB boot volume) to fit
- A ¥100/month budget alert and a nightly stop of the lab compartment's VMs live in a Terraform state separate from the
  experiment, so the safety net survives rebuilding the experiment
- Every cloud change followed "present the plan → explicit approval → apply exactly that plan"

## 10. Limitations

- One attack type (SSH login as a non-existent user), one region, one router, a single-VM SOAR
- 30 tests per condition; only C1 ran without the random wait (no phase bias was found)
- C3's T2 has ms resolution and TLS to CHR is not verified
- C5's load is light; we have not looked for the saturation point
- The waiting mechanisms of integratord and Shuffle in 6.1 are inferred from logs, not confirmed in source code

## 11. Next steps

- Shorten the hand-off: rewrite the integration script for the OS python3 with the standard library; shorten how often
  Shuffle (orborus) polls its queue
- Increase load to find where latency starts to grow
- Time to lift a block; multiple routers

## Appendix: reproducing

- Infrastructure: `infra/guardrails/` (budget, nightly stop), `infra/01-e2e-latency/terraform/` (VCN, VMs),
  `infra/01-e2e-latency/chr-image/` (CHR image)
- Device configuration: `infra/01-e2e-latency/routeros/`, `wazuh/`, `shuffle/`
- Measurement: run `experiments/01-e2e-latency/scripts/run_batch.sh <condition> 30` on the attacker, merge the timestamps with
  `collect_wazuh.py` and `collect_shuffle.py`, and summarize with `summarize.py`
- Figures: `experiments/01-e2e-latency/scripts/plot_results.py` (standard library only) regenerates the SVGs in `figures/`
