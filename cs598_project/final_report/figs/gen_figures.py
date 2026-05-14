#!/usr/bin/env python3
"""Generate all figures for the final report.

Each figure is written as a PDF in this directory. All input data is
hard-coded below (extracted from pesto-results/ via scripts/perf_analyze.py
and l2_audit.py). The README at the bottom of the file lists each
figure and what it claims.

Run: python3 gen_figures.py
Output: fig_<n>_<name>.pdf in this directory
"""

import os
import matplotlib
matplotlib.use("Agg")  # no display; pure PDF output
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Global style (USENIX two-column friendly, ~3.3" wide single-col figures)
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 9,
    "axes.labelsize": 9,
    "axes.titlesize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "lines.linewidth": 1.6,
    "lines.markersize": 5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,   # embed Type 1 fonts (avoid Type 3 warnings)
})

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

COL_WIDTH = 3.3   # inches (USENIX single column ~3.33")
DBL_WIDTH = 6.8   # inches (USENIX full-page width)

# ---------------------------------------------------------------------------
# Data, all from our 38-cluster experiment runs (paths in comments)
# ---------------------------------------------------------------------------

# Fig 1 -- crossover (origin Pesto vs our extension, f=1 NC sweep)
#   origin: pesto-results/20260513T13{56,40,42,43,44,45}*Z (N3 runs)
#   ours:   pesto-results/20260513T10{10,13,17,21,25,30,35}*Z (K2 sweep)
CROSSOVER = {
    "NC":         [6,    8,    12,   18,    24,    48],
    "origin_tps": [568,  757,  923,  970,   525,   69],   # T13xxxx N3
    "ours_tps":   [360,  499,  925,  1479,  2020,  18],   # K2
    "origin_p99": [18,   19,   40,   112,   1020,  1879],
    "ours_p99":   [20,   22,   20,   15,    15,    None],  # NC=48 ours crashed
}

# Fig 2 -- our saturation curve (NC sweep at f=1, full lab_ssh.txt)
SAT_OURS = {
    "NC":   [2,    4,    6,    8,    12,   18,    24,    32,    48,    64],
    "tput": [84,   190,  297,  421,  698,  1228,  1448,  1974,  2193,  2165],
    "p50":  [23.6, 21.0, 19.9, 18.8, 16.5, 14.2,  16.0,  13.2,  16.0,  15.1],
    "p95":  [30.7, 23.6, 22.4, 21.1, 19.1, 16.2,  19.2,  16.7,  22.5,  21.3],
    "p99":  [33.1, 24.4, 23.3, 22.3, 20.4, 17.5,  21.4,  20.2,  154,   105],
}

# Fig 3 -- WAN delay sweep (NC=24, f=1, shard-1 egress delay)
#   pesto-results/20260513T07{03,08,13,18,23,29}*Z and T022254 baseline
WAN = {
    "delay_ms": [0,    5,    10,   25,   50,   100,  200],
    "tput":     [1873, 1954, 1655, 1559, 1592, 1933, 1779],
    "p99":      [15.8, 16.0, 14.9, 18.5, 16.3, 16.8, 15.7],
}

# Fig 4 -- f-scaling cost (sister vs het, NC=6 baseline)
F_SCALE = {
    "f": [1, 2, 3],
    # f=1 sister/het from 18-cluster (304.6, 299.1) -- only place we have both
    "sister_tput": [304.6, 308.3, 257.5],
    "het_tput":    [299.1, 305.2, 271.9],
    "sister_err":  [0.3,   3.9,   5.5],
    "het_err":     [2.87,  5.7,   2.4],
    "verify_us":   [584,   872,   1281],
    # theoretical verify ratio relative to f=1 (2f+1 sigs):
    "verify_theoretical_ratio_vs_f1": [1.0, 5/3, 7/3],  # 1.0, 1.67, 2.33
    "verify_actual_ratio_vs_f1":      [1.0, 872/584, 1281/584],
}

# Fig 5 -- Byzantine cost (1 byz/shard at each f)
BYZ = {
    "f": [1, 2, 3],
    "honest":    [360.3, 305.2, 271.9],
    "omission":  [349.0, 312.2, 270.2],
    "twin":      [356.0, 314.4, 270.0],
}

# Fig 6 -- multi-shard TPC-C scaling
MSHARD = {
    "shards":           [2,    3,    4,    5],
    "tput":             [212,  240,  227,  230],
    "cross_shard_txns": [621,  948,  951,  1029],
}


# ---------------------------------------------------------------------------
# Figure 1: throughput crossover (origin Pesto vs ours)
# ---------------------------------------------------------------------------
def fig_crossover():
    fig, ax = plt.subplots(figsize=(COL_WIDTH, 2.2))
    NC = CROSSOVER["NC"]
    ax.plot(NC, CROSSOVER["origin_tps"], "o-", color="#444444",
            label="Original Pesto", markerfacecolor="white",
            markeredgewidth=1.4)
    ax.plot(NC, CROSSOVER["ours_tps"], "s-", color="#c0392b",
            label="Our extension")
    # crossover marker around NC=12
    ax.axvline(12, color="#888888", linestyle=":", linewidth=0.8)
    ax.text(12.4, 1700, "crossover", fontsize=7, color="#666666",
            rotation=90, va="top")
    ax.set_xlabel("Client count (NC)")
    ax.set_ylabel("Throughput (tx/s)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(NC)
    ax.set_xticklabels([str(x) for x in NC])
    ax.set_ylim(0, 2200)
    ax.legend(loc="upper left", frameon=False)
    fig.savefig(os.path.join(OUT_DIR, "fig_crossover.pdf"))
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: our saturation curve -- twin axes throughput + P99
# ---------------------------------------------------------------------------
def fig_saturation():
    # Wider figure so annotations have room.
    fig, ax1 = plt.subplots(figsize=(COL_WIDTH + 0.4, 2.4))
    NC = SAT_OURS["NC"]
    color1 = "#2c3e50"
    color2 = "#c0392b"
    ax1.plot(NC, SAT_OURS["tput"], "o-", color=color1, label="Throughput")
    ax1.set_xlabel("Client count (NC)")
    ax1.set_ylabel("Throughput (tx/s)", color=color1)
    ax1.set_xscale("log", base=2)
    ax1.set_xticks(NC)
    ax1.set_xticklabels([str(x) for x in NC])
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.set_ylim(0, 2800)         # extra headroom above 2193 for label
    # Mark the peak with a label well above so it doesn't sit on top of points
    peak_idx = SAT_OURS["tput"].index(max(SAT_OURS["tput"]))
    ax1.annotate(f'peak {SAT_OURS["tput"][peak_idx]} tx/s',
                 xy=(NC[peak_idx], SAT_OURS["tput"][peak_idx]),
                 xytext=(NC[2], 2550),   # above NC=6 area, off the curve
                 fontsize=7, color=color1,
                 arrowprops=dict(arrowstyle="->", color=color1, lw=0.6,
                                 connectionstyle="arc3,rad=-0.18"))

    ax2 = ax1.twinx()
    ax2.spines["right"].set_visible(True)
    ax2.plot(NC, SAT_OURS["p99"], "x--", color=color2, label="P99",
             markersize=6)
    ax2.set_ylabel("P99 latency (ms)", color=color2,
                   labelpad=2)
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.set_yscale("log")
    # Shrink right axis range so the dashed line sits below the throughput
    # curve and the right-side label is not crowded by data points.
    ax2.set_ylim(8, 3000)
    fig.savefig(os.path.join(OUT_DIR, "fig_saturation.pdf"))
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 3: WAN delay tolerance
# ---------------------------------------------------------------------------
def fig_wan():
    fig, ax = plt.subplots(figsize=(COL_WIDTH, 2.2))
    delay = WAN["delay_ms"]
    tput = WAN["tput"]
    baseline = tput[0]
    # Use categorical x positions to avoid symlog overlap of "100"/"200"
    xs = list(range(len(delay)))
    ax.plot(xs, tput, "o-", color="#34495e")
    ax.axhline(baseline, color="#888888", linestyle=":", linewidth=0.8,
               label=f"no-delay baseline ({baseline} tx/s)")
    ax.set_xlabel("Shard-1 egress delay (ms)")
    ax.set_ylabel("Throughput (tx/s)")
    ax.set_xticks(xs)
    ax.set_xticklabels([str(d) for d in delay])
    ax.set_ylim(1300, 2100)   # zoom y range to show the dip clearly
    # Annotate the worst point
    dip_idx = tput.index(min(tput[1:]))
    ax.annotate(f"min: {tput[dip_idx]}",
                xy=(dip_idx, tput[dip_idx]),
                xytext=(dip_idx + 0.3, tput[dip_idx] - 100),
                fontsize=7, color="#c0392b",
                arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.6))
    ax.legend(loc="upper right", frameon=False)
    fig.savefig(os.path.join(OUT_DIR, "fig_wan.pdf"))
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 4: sister-vs-het ablation at f = 1, 2, 3 (grouped bars + verify mu_s)
# ---------------------------------------------------------------------------
def fig_fscale_ablation():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(DBL_WIDTH, 2.4))

    # Left: throughput grouped bars
    x = np.arange(len(F_SCALE["f"]))
    width = 0.36
    ax1.bar(x - width/2, F_SCALE["sister_tput"], width,
            yerr=F_SCALE["sister_err"], capsize=3,
            color="#3498db", label="Sister-replica")
    ax1.bar(x + width/2, F_SCALE["het_tput"], width,
            yerr=F_SCALE["het_err"], capsize=3,
            color="#e67e22", label="Heterogeneous")
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"f={f}" for f in F_SCALE["f"]])
    ax1.set_ylabel("Throughput (tx/s)")
    ax1.set_ylim(0, 380)
    ax1.legend(loc="upper right", frameon=False)
    ax1.set_title("(a) Sister vs heterogeneous, NC=6")

    # Right: verify mu_s, actual vs theoretical (2f+1 ratio)
    ax2.plot(F_SCALE["f"], F_SCALE["verify_us"], "s-",
             color="#c0392b", label="Measured verify $\\mu s$")
    # theoretical curve scaled to f=1
    theor = [F_SCALE["verify_us"][0] * r
             for r in F_SCALE["verify_theoretical_ratio_vs_f1"]]
    ax2.plot(F_SCALE["f"], theor, "o--",
             color="#7f8c8d", label="Linear in $2f{+}1$")
    ax2.set_xticks(F_SCALE["f"])
    ax2.set_xticklabels([f"f={f}" for f in F_SCALE["f"]])
    ax2.set_ylabel("Verify cost ($\\mu s$ per cert)")
    ax2.legend(loc="upper left", frameon=False)
    ax2.set_title("(b) Crypto cost scales linearly in $2f{+}1$")
    fig.savefig(os.path.join(OUT_DIR, "fig_fscale_ablation.pdf"))
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 5: Byzantine cost at f = 1, 2, 3 (grouped bars)
# ---------------------------------------------------------------------------
def fig_byz():
    fig, ax = plt.subplots(figsize=(COL_WIDTH, 2.4))
    x = np.arange(len(BYZ["f"]))
    width = 0.27
    ax.bar(x - width, BYZ["honest"],   width,
           color="#27ae60", label="Honest")
    ax.bar(x,         BYZ["omission"], width,
           color="#7f8c8d", label="1 omission/shard")
    ax.bar(x + width, BYZ["twin"],     width,
           color="#c0392b", label="1 twin/shard")
    ax.set_xticks(x)
    ax.set_xticklabels([f"f={f}" for f in BYZ["f"]])
    ax.set_ylabel("Throughput (tx/s)")
    # Expand y so legend can sit above the bars without overlap
    ax.set_ylim(0, 480)
    # Put legend ABOVE the plot area so it never crosses the bars
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18),
              frameon=False, ncol=3, fontsize=7,
              handletextpad=0.4, columnspacing=0.9)
    fig.savefig(os.path.join(OUT_DIR, "fig_byz.pdf"))
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 6: multi-shard scaling (TPC-C, 2-5 shards)
# ---------------------------------------------------------------------------
def fig_multishard():
    # A bit taller to fit the legend above the bars cleanly
    fig, ax1 = plt.subplots(figsize=(COL_WIDTH, 2.4))
    shards = MSHARD["shards"]
    color1 = "#2980b9"
    color2 = "#16a085"
    ax1.bar([s - 0.18 for s in shards], MSHARD["tput"], 0.36,
            color=color1)
    ax1.set_xlabel("Shard count")
    ax1.set_ylabel("Throughput (tx/s)", color=color1)
    ax1.tick_params(axis="y", labelcolor=color1)
    ax1.set_xticks(shards)
    ax1.set_ylim(0, 340)
    ax2 = ax1.twinx()
    ax2.spines["right"].set_visible(True)
    ax2.bar([s + 0.18 for s in shards], MSHARD["cross_shard_txns"], 0.36,
            color=color2)
    ax2.set_ylabel("Cross-shard txns / 60 s", color=color2)
    ax2.tick_params(axis="y", labelcolor=color2)
    ax2.set_ylim(0, 1200)
    # Single combined legend above the axes
    handles = [plt.Rectangle((0, 0), 1, 1, fc=color1),
               plt.Rectangle((0, 0), 1, 1, fc=color2)]
    ax1.legend(handles, ["Throughput (left)", "Cross-shard txns (right)"],
               loc="upper center", bbox_to_anchor=(0.5, 1.16),
               frameon=False, fontsize=7, ncol=2,
               handletextpad=0.4, columnspacing=1.0)
    fig.savefig(os.path.join(OUT_DIR, "fig_multishard.pdf"))
    plt.close(fig)


if __name__ == "__main__":
    fig_crossover()
    fig_saturation()
    fig_wan()
    fig_fscale_ablation()
    fig_byz()
    fig_multishard()
    print("Wrote:")
    for f in sorted(os.listdir(OUT_DIR)):
        if f.endswith(".pdf"):
            full = os.path.join(OUT_DIR, f)
            print(f"  {full}  ({os.path.getsize(full)} bytes)")
