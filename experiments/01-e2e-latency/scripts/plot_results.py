#!/usr/bin/env python3
"""Generate the article figures from raw/*/trial.json (stdlib only, SVG out).

    python3 plot_results.py                      # -> articles/01-e2e-latency/figures/*.svg

Figures
  fig1-segments.svg  stacked horizontal bars: MEAN of each segment per condition
                     (means are additive, so the bar length equals mean E2E;
                     medians are not additive and would not sum to the E2E median)
  fig2-e2e-cdf.svg   empirical CDF of D_e2e per condition, p50/p95 guides
  fig3-dispatch-breakdown.svg  C1 vs C5: mean Wazuh-side / Shuffle-side parts of
                     D_dispatch (input: results/dispatch_breakdown.csv, made by
                     breakdown_dispatch.py from Shuffle logs)
  fig4-phase.svg     circular dot plot of T0 phase in the agent's 2 s read loop,
                     first C4 run vs C4-jitter, with R and Rayleigh p

Design (dataviz method): categorical slots in fixed order, validated for light
and dark (adjacent pairs). Light slots 3-5 are below 3:1 contrast, so every
series is direct-labelled and the article keeps the numeric tables. Light and
dark palettes are both embedded (prefers-color-scheme). Each mark has a
<title> so browsers show a native tooltip.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "raw"
OUT = HERE.parent.parent.parent / "articles" / "01-e2e-latency" / "figures"

# condition id in data -> label shown in figures (C4 uses the jitter re-run)
CONDITIONS = [
    ("C1", "C1 baseline (Shuffle, raw drop)"),
    ("C2", "C2 filter drop"),
    ("C3", "C3 Shuffle 2 actions"),
    ("C4-jitter", "C4 Wazuh AR → CHR (no SOAR)"),
    ("C5", "C5 +20 alerts/s background"),
]
SEGMENTS = [  # (key, label, (end, start))
    ("detect", "Detect (T0→T1_detect)", ("t1_detect_ns", "t0_ns")),
    ("dispatch", "Dispatch (→T1_soar)", ("t1_soar_ns", "t1_detect_ns")),
    ("api", "API (→T2)", ("t2_ns", "t1_soar_ns")),
    ("enforce", "Enforce (→T3)", ("t3_ns", "t2_ns")),
]

STYLE = """
<style>
  svg { --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --grid:#e4e3df;
        --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; }
  @media (prefers-color-scheme: dark) {
    svg { --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --grid:#3a3a37;
          --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; }
  }
  .bg { fill: var(--surface); }
  text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink); }
  .t-title { font-size: 15px; font-weight: 600; }
  .t-sub, .t-axis, .t-tick { font-size: 11px; fill: var(--ink2); }
  .t-label { font-size: 12px; }
  .t-val { font-size: 11px; fill: var(--ink2); }
  .grid { stroke: var(--grid); stroke-width: 1; }
  .axis { stroke: var(--ink2); stroke-width: 1; }
  .guide { stroke: var(--ink2); stroke-width: 1; stroke-dasharray: 3 3; opacity: .6; }
</style>
"""


def load() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for f in sorted(RAW.glob("*/trial.json")):
        t = json.loads(f.read_text())
        if t.get("blocked") and all(t.get(k) for k in ("t0_ns", "t1_detect_ns", "t1_soar_ns", "t2_ns", "t3_ns")):
            by.setdefault(t["condition"], []).append(t)
    return by


def ms(t, end, start) -> float:
    return (t[end] - t[start]) / 1e6


def nice_ticks(vmax: float, step: float) -> list[float]:
    n = int(vmax // step) + 1
    return [i * step for i in range(n + 1)]


def svg(w: int, h: int, body: list[str], title: str, desc: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-labelledby="t d"><title id="t">{escape(title)}</title><desc id="d">{escape(desc)}</desc>'
            f'{STYLE}<rect class="bg" x="0" y="0" width="{w}" height="{h}"/>' + "".join(body) + "</svg>\n")


def fig_segments(by) -> str:
    W, left, right, top = 880, 250, 40, 92
    bar_h, gap = 26, 18
    rows = [(cid, lab, {k: st.fmean(ms(t, *se) for t in by[cid]) for k, _, se in SEGMENTS}) for cid, lab in CONDITIONS if cid in by]
    vmax = max(sum(r[2].values()) for r in rows)
    step = 1000
    ticks = nice_ticks(vmax, step)
    xmax = ticks[-1]
    pw = W - left - right
    x = lambda v: left + v / xmax * pw
    H = top + len(rows) * (bar_h + gap) + 50
    b = [f'<text class="t-title" x="24" y="30">Where the time goes: mean latency per segment</text>',
         f'<text class="t-sub" x="24" y="48">n = 30 per condition · bar length = mean E2E (T0→T3) · C3: API segment includes the wait before the 2nd action</text>']
    # legend (one row, above the plot)
    lx = 24
    for i, (_, lab, _) in enumerate(SEGMENTS):
        b.append(f'<rect x="{lx}" y="62" width="12" height="12" rx="3" fill="var(--s{i+1})"/>'
                 f'<text class="t-label" x="{lx+18}" y="72">{escape(lab)}</text>')
        lx += 18 + 7.2 * len(lab) + 22
    for tv in ticks:
        b.append(f'<line class="grid" x1="{x(tv):.1f}" y1="{top-6}" x2="{x(tv):.1f}" y2="{H-44}"/>'
                 f'<text class="t-tick" x="{x(tv):.1f}" y="{H-28}" text-anchor="middle">{tv/1000:.0f} s</text>')
    for r, (cid, lab, means) in enumerate(rows):
        y = top + r * (bar_h + gap)
        b.append(f'<text class="t-label" x="{left-12}" y="{y+bar_h/2+4}" text-anchor="end">{escape(lab)}</text>')
        acc = 0.0
        for i, (k, slab, _) in enumerate(SEGMENTS):
            v = means[k]
            x0, x1 = x(acc), x(acc + v)
            wd = max(x1 - x0 - 2, 0.8)  # 2px surface gap between fills
            last = i == len(SEGMENTS) - 1
            b.append(f'<rect x="{x0:.1f}" y="{y}" width="{wd:.1f}" height="{bar_h}" rx="{4 if last else 0}" fill="var(--s{i+1})">'
                     f'<title>{escape(cid)} · {escape(slab)}: {v:,.0f} ms (mean)</title></rect>')
            acc += v
        b.append(f'<text class="t-val" x="{x(acc)+8:.1f}" y="{y+bar_h/2+4}">{acc:,.0f} ms</text>')
    b.append(f'<line class="axis" x1="{left}" y1="{H-44}" x2="{W-right}" y2="{H-44}"/>')
    return svg(W, H, b, "Mean latency per segment by condition",
               "Stacked horizontal bars of mean detect, dispatch, API and enforce time for conditions C1 to C5.")


def fig_cdf(by) -> str:
    W, H, left, right, top, bottom = 880, 460, 64, 210, 70, 56
    series = [(cid, lab, sorted(ms(t, "t3_ns", "t0_ns") for t in by[cid])) for cid, lab in CONDITIONS if cid in by]
    xmax = nice_ticks(max(v[-1] for _, _, v in series), 1000)[-1]
    pw, ph = W - left - right, H - top - bottom
    x = lambda v: left + v / xmax * pw
    y = lambda p: top + (1 - p) * ph
    b = [f'<text class="t-title" x="24" y="30">How fast is the attacker cut off? E2E latency (T0→T3)</text>',
         f'<text class="t-sub" x="24" y="48">Empirical CDF, n = 30 per condition · dashed lines: 50th and 95th percentile</text>']
    for tv in nice_ticks(xmax - 1, 1000):
        b.append(f'<line class="grid" x1="{x(tv):.1f}" y1="{top}" x2="{x(tv):.1f}" y2="{top+ph}"/>'
                 f'<text class="t-tick" x="{x(tv):.1f}" y="{top+ph+18}" text-anchor="middle">{tv/1000:.0f} s</text>')
    for p in (0, 0.25, 0.5, 0.75, 1.0):
        b.append(f'<text class="t-tick" x="{left-8}" y="{y(p)+4:.1f}" text-anchor="end">{p:.0%}</text>')
    for p in (0.5, 0.95):
        b.append(f'<line class="guide" x1="{left}" y1="{y(p):.1f}" x2="{left+pw}" y2="{y(p):.1f}"/>')
    b.append(f'<line class="axis" x1="{left}" y1="{top+ph}" x2="{left+pw}" y2="{top+ph}"/>'
             f'<text class="t-axis" x="{left+pw/2}" y="{H-14}" text-anchor="middle">E2E latency (attacker clock, ±10 ms)</text>')
    label_y = []
    for i, (cid, lab, v) in enumerate(series):
        n = len(v)
        pts = [f"{x(0):.1f},{y(0):.1f}", f"{x(v[0]):.1f},{y(0):.1f}"]
        for k, val in enumerate(v):
            pts.append(f"{x(val):.1f},{y(k/n):.1f}")
            pts.append(f"{x(val):.1f},{y((k+1)/n):.1f}")
        pts.append(f"{x(xmax):.1f},{y(1):.1f}")
        p50, p95 = st.median(v), v[min(n - 1, round(0.95 * (n - 1)))]
        b.append(f'<polyline fill="none" stroke="var(--s{i+1})" stroke-width="2" stroke-linejoin="round" points="{" ".join(pts)}">'
                 f'<title>{escape(lab)}: p50 {p50:,.0f} ms · p95 {p95:,.0f} ms · max {v[-1]:,.0f} ms</title></polyline>')
        # p50 marker (>= 8px) on each curve
        b.append(f'<circle cx="{x(p50):.1f}" cy="{y(0.5):.1f}" r="4.5" fill="var(--s{i+1})" stroke="var(--surface)" stroke-width="2">'
                 f'<title>{escape(cid)} median {p50:,.0f} ms</title></circle>')
        label_y.append([y(1) + 0, i, lab, p50])
    # direct labels in the right margin, ordered by median, spaced to avoid collisions
    order = sorted(range(len(series)), key=lambda i: series[i][2][len(series[i][2]) // 2])
    for rank, i in enumerate(order):
        cid, lab, v = series[i]
        ly = top + 14 + rank * 22
        b.append(f'<rect x="{left+pw+16}" y="{ly-9}" width="12" height="3" rx="1.5" fill="var(--s{i+1})"/>'
                 f'<text class="t-label" x="{left+pw+34}" y="{ly-3}">{escape(cid.replace("-jitter", ""))} · p50 {st.median(v)/1000:.2f} s</text>')
    return svg(W, H, b, "E2E latency CDF by condition",
               "Empirical cumulative distribution of end-to-end block latency for conditions C1 to C5.")


BREAKDOWN = HERE.parent / "results" / "dispatch_breakdown.csv"
DISPATCH_PARTS = [  # (label, columns summed) - means are additive
    ("Wazuh: alert → webhook", ["wazuh_alert_to_webhook_ms"]),
    ("Shuffle: webhook → worker picks it up", ["shuffle_webhook_to_created_ms", "shuffle_queue_ms"]),
    ("Shuffle: worker → app → code starts", ["shuffle_worker_to_app_ms", "shuffle_app_to_code_ms"]),
]


def fig_dispatch(path: Path) -> str:
    import csv
    rows = list(csv.DictReader(path.open()))
    conds = [("C1", "C1 baseline"), ("C5", "C5 +20 alerts/s")]
    data = []
    for cid, lab in conds:
        rr = [r for r in rows if r["condition"] == cid]
        data.append((cid, lab, len(rr), [st.fmean(sum(float(r[c]) for c in cols) for r in rr) for _, cols in DISPATCH_PARTS]))
    W, left, right, top, bar_h, gap = 880, 150, 90, 120, 34, 46
    xmax = nice_ticks(max(sum(v) for *_, v in data), 1000)[-1]
    pw = W - left - right
    x = lambda v: left + v / xmax * pw
    H = top + len(data) * (bar_h + gap) + 40
    b = ['<text class="t-title" x="24" y="30">Inside the dispatch segment: only the Wazuh side gets faster under load</text>',
         '<text class="t-sub" x="24" y="48">Mean ms per part, n = 30 each · from Shuffle backend/worker logs (ns) and Wazuh alert timestamps</text>']
    lx = 24
    for i, (lab, _) in enumerate(DISPATCH_PARTS):
        b.append(f'<rect x="{lx}" y="64" width="12" height="12" rx="3" fill="var(--s{i+1})"/>'
                 f'<text class="t-label" x="{lx+18}" y="74">{escape(lab)}</text>')
        lx += 18 + 6.9 * len(lab) + 22
    for tv in nice_ticks(xmax - 1, 1000):
        b.append(f'<line class="grid" x1="{x(tv):.1f}" y1="{top-26}" x2="{x(tv):.1f}" y2="{H-34}"/>'
                 f'<text class="t-tick" x="{x(tv):.1f}" y="{H-18}" text-anchor="middle">{tv/1000:.0f} s</text>')
    for r, (cid, lab, n, parts) in enumerate(data):
        y = top + r * (bar_h + gap)
        b.append(f'<text class="t-label" x="{left-12}" y="{y+bar_h/2+4}" text-anchor="end">{escape(lab)}</text>')
        acc = 0.0
        for i, v in enumerate(parts):
            x0, x1 = x(acc), x(acc + v)
            last = i == len(parts) - 1
            b.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1-x0-2, .8):.1f}" height="{bar_h}" rx="{4 if last else 0}" fill="var(--s{i+1})">'
                     f'<title>{escape(cid)} · {escape(DISPATCH_PARTS[i][0])}: {v:,.0f} ms (mean, n={n})</title></rect>'
                     f'<text class="t-val" x="{(x0+x1)/2:.1f}" y="{y-6}" text-anchor="middle">{v:,.0f}</text>')
            acc += v
        b.append(f'<text class="t-val" x="{x(acc)+8:.1f}" y="{y+bar_h/2+4}">= {acc:,.0f} ms</text>')
    b.append(f'<line class="axis" x1="{left}" y1="{H-34}" x2="{W-right}" y2="{H-34}"/>')
    return svg(W, H, b, "Dispatch breakdown, C1 vs C5",
               "Stacked bars of the mean Wazuh-side and Shuffle-side parts of the dispatch segment for C1 and C5.")


def phase_stats(t0s: list[int], period: float = 2.0) -> tuple[list[float], float, float, float]:
    import math
    ang = [2 * math.pi * ((v / 1e9) % period) / period for v in t0s]
    n = len(ang)
    cx, cy = sum(map(math.cos, ang)) / n, sum(map(math.sin, ang)) / n
    r = math.hypot(cx, cy)
    z = n * r * r
    p = math.exp(math.sqrt(1 + 4 * n + 4 * (n * n - z * n)) - (1 + 2 * n))
    return ang, r, p, math.atan2(cy, cx)


def fig_phase(by) -> str:
    import math
    panels = [("C4", "First C4 run (fixed cadence)", "var(--ink2)"),
              ("C4-jitter", "C4 re-run with 0–4 s random wait", "var(--s4)")]
    W, H, R0 = 880, 430, 120
    b = ['<text class="t-title" x="24" y="30">Phase-locking: test start times vs the agent\'s 2 s journald read loop</text>',
         '<text class="t-sub" x="24" y="48">Each dot = one test, placed at (T0 mod 2 s) · arrow = mean resultant vector (length R) · n = 30 each</text>']
    for k, (cid, title, color) in enumerate(panels):
        cx, cy = 220 + k * 440, 240
        ang, r, p, mean_a = phase_stats([t["t0_ns"] for t in by.get(cid, [])])
        b.append(f'<text class="t-label" x="{cx}" y="84" text-anchor="middle" style="font-weight:600">{escape(title)}</text>')
        b.append(f'<circle cx="{cx}" cy="{cy}" r="{R0}" fill="none" class="grid" style="stroke:var(--grid);stroke-width:1.5"/>')
        for q, lab in enumerate(("0 s", "0.5 s", "1 s", "1.5 s")):
            a = q * math.pi / 2
            tx, ty = cx + (R0 + 22) * math.sin(a), cy - (R0 + 22) * math.cos(a) + 4
            b.append(f'<text class="t-tick" x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle">{lab}</text>')
        # angle 0 at 12 o'clock, clockwise; stack coincident dots outward to avoid overlap
        placed: list[tuple[float, float]] = []
        for a in sorted(ang):
            rad = R0
            while any(abs(rad - pr) < 1 and abs(math.remainder(a - pa, 2 * math.pi)) * R0 < 9 for pa, pr in placed):
                rad -= 10
            placed.append((a, rad))
            px, py = cx + rad * math.sin(a), cy - rad * math.cos(a)
            sec = a / (2 * math.pi) * 2
            b.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{color}" stroke="var(--surface)" stroke-width="2">'
                     f'<title>{escape(cid)} test at phase {sec:.2f} s</title></circle>')
        ex, ey = cx + r * R0 * math.sin(mean_a), cy - r * R0 * math.cos(mean_a)
        b.append(f'<line x1="{cx}" y1="{cy}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="var(--ink)" stroke-width="2"/>'
                 f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="var(--ink)"><title>R = {r:.3f}</title></circle>')
        verdict = "locked" if p < 0.05 else "uniform (no lock)"
        b.append(f'<text class="t-label" x="{cx}" y="{cy+R0+52}" text-anchor="middle">R = {r:.2f} · Rayleigh p = {p:.2g} · {verdict}</text>')
    return svg(W, H, b, "Phase concentration of test starts",
               "Two circular dot plots of test start phase within a 2 second period: the first C4 run is concentrated, the re-run with random wait is uniform.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    by = load()
    args.out.mkdir(parents=True, exist_ok=True)
    figs = {
        "fig1-segments.svg": fig_segments(by),
        "fig2-e2e-cdf.svg": fig_cdf(by),
        "fig3-dispatch-breakdown.svg": fig_dispatch(BREAKDOWN),
        "fig4-phase.svg": fig_phase(by),
    }
    for name, body in figs.items():
        (args.out / name).write_text(body)
    print("wrote", ", ".join(figs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
