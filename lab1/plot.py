#!/usr/bin/env python3
"""Reads results/raw_*.txt, writes images/*.png and results/summary.json."""
import json, re, statistics as st, sys
from collections import defaultdict
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
RES, IMG = ROOT / "results", ROOT.parent / "images"
IMG.mkdir(exist_ok=True)
BLUE, GRAY, INK = "#2a6fbb", "#8a8f98", "#222222"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRAY, "axes.labelcolor": INK,
                     "xtick.color": INK, "ytick.color": INK, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e4e6ea",
                     "grid.linewidth": 0.6, "axes.axisbelow": True})

def parse(name):
    p = RES / name
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if line.startswith("RESULT"):
            rows.append({k: v for k, v in re.findall(r"(\w+)=(\S+)", line)})
    return rows

def by_threads(rows):
    g = defaultdict(list)
    for r in rows:
        g[int(r["threads"])].append(r)
    out = {}
    for t, rs in sorted(g.items()):
        out[t] = {"time_ms": st.median(float(r["time_ms"]) for r in rs),
                  "peak_mb": max(float(r["peak_mb"]) for r in rs),
                  "runs": len(rs),
                  "totals": sorted({(r["neg"], r["pos"], r["zero"], r["total"]) for r in rs})}
    return out

def three_panel(data, title, fname):
    ts = list(data)
    time = [data[t]["time_ms"] / 1000 for t in ts]
    base = data[ts[0]]["time_ms"] / 1000
    spd = [base / x for x in time]
    mem = [data[t]["peak_mb"] for t in ts]
    fig, ax = plt.subplots(1, 3, figsize=(11, 3.1))
    for a, y, lab in ((ax[0], time, "Execution time (s)"), (ax[1], spd, "Speed-up vs. 1 thread"),
                      (ax[2], mem, "Peak memory (MB)")):
        a.plot(ts, y, "-o", color=BLUE, lw=1.6, ms=4.5, mfc=BLUE, mec="white", mew=0.8,
               label="measured")
        a.set_xscale("log", base=2)
        a.set_xticks(ts); a.set_xticklabels([str(t) for t in ts])
        a.set_xlabel("Threads"); a.set_ylabel(lab)
        a.set_ylim(bottom=0)
    ax[1].plot(ts, [t / ts[0] for t in ts], "--", color=GRAY, lw=1, label="ideal (linear)")
    ax[1].set_ylim(0, max(spd) * 1.25)
    ax[1].set_yscale("linear")
    ax[1].legend(frameon=False, loc="upper left")
    ax[0].set_title(title, loc="left", fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(IMG / fname, dpi=200)
    plt.close(fig)

summary = {}

a = by_threads(parse("raw_1a.txt"))
if a:
    three_panel(a, "Task 1a: counting with threads (median of 5 runs)", "task1a.png")
    summary["1a"] = a

c = by_threads(parse("raw_1c.txt"))
if c:
    three_panel(c, "Task 1c: producer and consumers (median of 3 runs)", "task1c.png")
    summary["1c"] = c

b_rows = parse("raw_1b.txt")
if b_rows:
    g = defaultdict(list)
    for r in b_rows:
        g[r["variant"]].append(r)
    order = ["unsync", "mutex", "local"]
    names = {"unsync": "1. shared,\nno sync", "mutex": "2. shared,\nmutex", "local": "3. per-thread\ncounters"}
    meds = [st.median(float(r["time_ms"]) for r in g[v]) / 1000 for v in order if v in g]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    bars = ax.bar([names[v] for v in order if v in g], meds, color=BLUE, width=0.5)
    ax.set_yscale("log"); ax.set_ylabel("Execution time (s, log scale)")
    for bar, m in zip(bars, meds):
        ax.text(bar.get_x() + bar.get_width() / 2, m * 1.15, f"{m:.3f}", ha="center", fontsize=8, color=INK)
    ax.set_ylim(top=max(meds) * 3)
    fig.tight_layout(); fig.savefig(IMG / "task1b.png", dpi=200); plt.close(fig)
    summary["1b"] = {v: [{"time_ms": float(r["time_ms"]), "neg": r["neg"], "pos": r["pos"],
                          "zero": r["zero"], "total": r["total"]} for r in g[v]] for v in g}

q6 = parse("raw_1c_q6.txt")
if q6:
    summary["1c_q6"] = q6

for key, fname, title in (("raw_2_usb.txt", "task2_usb.png", "Task 2: USB drive"),
                          ("raw_2_local.txt", "task2_local.png", "Task 2: internal SSD (reference)")):
    d = by_threads(parse(key))
    if d:
        three_panel(d, title, fname)
        summary[key] = d

(RES / "summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({k: (v if k in ("1c_q6",) else "ok") for k, v in summary.items()}, indent=1))
