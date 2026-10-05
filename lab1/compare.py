#!/usr/bin/env python3
"""C vs Python comparison -> images/compare_c_vs_python.png + printed table."""
import re, statistics as st
from collections import defaultdict
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
R = Path(__file__).resolve().parent / "results"
def load(n):
    g = defaultdict(list)
    for l in (R / n).read_text().splitlines():
        if l.startswith("RESULT"):
            d = dict(re.findall(r"(\w+)=(\S+)", l)); g[(d["variant"], int(d["threads"]))].append(d)
    return g
def med(g, k): return st.median(float(d["time_ms"]) for d in g[k]) / 1000
def peak(g, k): return max(float(d["peak_mb"]) for d in g[k])
BLUE, ORANGE, GRAY = "#2a6fbb", "#c8661a", "#8a8f98"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e4e6ea", "axes.axisbelow": True})
fig, ax = plt.subplots(1, 3, figsize=(11, 3.2))
for a, task, title in ((ax[0], "1a", "Task 1a"), (ax[1], "1c", "Task 1c")):
    c, p = load(f"raw_{task}.txt"), load(f"py_raw_{task}.txt")
    ts = sorted(t for _, t in c)
    k = "split-file" if task == "1a" else "producer-consumer"
    a.plot(ts, [med(c, (k, t)) for t in ts], "-o", color=BLUE, ms=4, label="C (pthreads)")
    a.plot(ts, [med(p, (k, t)) for t in ts], "-s", color=ORANGE, ms=4, label="Python (GIL)")
    a.set_xscale("log", base=2); a.set_xticks(ts); a.set_xticklabels(ts)
    a.set_yscale("log"); a.set_xlabel("Threads"); a.set_ylabel("Time (s, log)"); a.set_title(title, loc="left")
    a.legend(frameon=False)
    print(task, "threads  C(s)  Py(s)  Py/C  PyPeak(MB)")
    for t in ts:
        print(f"  {t:3d}  {med(c,(k,t)):7.3f} {med(p,(k,t)):7.3f} {med(p,(k,t))/med(c,(k,t)):6.1f}x {peak(p,(k,t)):8.1f}")
c, p = load("raw_1b.txt"), load("py_raw_1b.txt")
vs = ["unsync", "mutex", "local"]
import numpy as np
x = np.arange(3); w = 0.36
ax[2].bar(x - w/2, [med(c, (v, 8)) for v in vs], w, color=BLUE, label="C")
ax[2].bar(x + w/2, [med(p, (v, 8)) for v in vs], w, color=ORANGE, label="Python")
ax[2].set_xticks(x); ax[2].set_xticklabels(["no sync", "mutex", "per-thread"]); ax[2].set_yscale("log")
ax[2].set_ylabel("Time (s, log)"); ax[2].set_title("Task 1b (8 threads)", loc="left"); ax[2].legend(frameon=False)
print("1b  version   C(s)   Py(s)   Py total(unsync)")
for v in vs: print(f"  {v:7s} {med(c,(v,8)):7.3f} {med(p,(v,8)):7.3f}")
fig.tight_layout(); fig.savefig(R.parent.parent / "images" / "compare_c_vs_python.png", dpi=200)
