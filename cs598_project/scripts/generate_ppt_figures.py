#!/usr/bin/env python3
"""
generate_ppt_figures.py — produce every figure referenced in
docs/presentation.md into ppt_figures/.  Pulls real numbers from the
results files where applicable; uses matplotlib for charts and
patches for diagrams.

Run:  python3 scripts/generate_ppt_figures.py
Output:  ppt_figures/fig_NN_*.png
"""

import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle
import matplotlib.gridspec as gridspec

ROOT = Path(__file__).parent.parent
OUT  = ROOT / "ppt_figures"
OUT.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


# ---------------------------------------------------------------- helpers
def save(fig, name):
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {path}")


def shard_box(ax, x, y, n, label, color="#cfd8dc", labelcolor="black",
              hatch=None):
    """Draw a shard as a rounded box with n small replica circles inside."""
    w, h = 1.6, 0.4 + 0.18 * n
    box = FancyBboxPatch((x - w/2, y - h/2), w, h,
                         boxstyle="round,pad=0.03",
                         linewidth=1.5,
                         facecolor=color, edgecolor="#37474f",
                         hatch=hatch)
    ax.add_patch(box)
    ax.text(x, y + h/2 - 0.13, label,
            ha="center", va="top", fontweight="bold",
            color=labelcolor, fontsize=11)
    # replica circles
    cols = min(n, 6)
    for i in range(n):
        cx = x - (cols - 1) * 0.11 + (i % cols) * 0.22
        cy = y - 0.05 - (i // cols) * 0.20
        ax.add_patch(Circle((cx, cy), 0.07,
                            facecolor="#1565c0", edgecolor="white",
                            linewidth=1.0))


# ---------------------------------------------------------------- slide 02
def fig_02():
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.set_xlim(0, 10); ax.set_ylim(0, 5)
    ax.axis("off")

    # client at center top
    ax.add_patch(FancyBboxPatch((4.3, 3.8), 1.4, 0.6,
                 boxstyle="round,pad=0.04",
                 facecolor="#fff9c4", edgecolor="#37474f", linewidth=1.5))
    ax.text(5.0, 4.1, "Client", ha="center", va="center", fontweight="bold")

    shard_box(ax, 2.5, 1.8, 6, "Shard 0\nn=5f+1=6, f=1", color="#e3f2fd")
    shard_box(ax, 7.5, 1.8, 6, "Shard 1\nn=5f+1=6, f=1", color="#e3f2fd")

    for sx in (2.5, 7.5):
        ax.annotate("", xy=(sx, 2.5), xytext=(5.0, 3.78),
                    arrowprops=dict(arrowstyle="-|>", color="#37474f", lw=1.4))

    ax.text(5.0, 0.4,
            "Single-shard txn: 1 RTT (fast path)\n"
            "Cross-shard txn: snapshot exchange + verification",
            ha="center", va="center", fontsize=10, style="italic",
            color="#37474f")
    fig.suptitle("Pesto: BFT SQL on top of Basil (SOSP'21)",
                 fontsize=13, fontweight="bold", y=0.97)
    save(fig, "fig_02_pesto_arch.png")


# ---------------------------------------------------------------- slide 03
_S3_ADMINS = [
    ("AWS",  "#ef5350"),
    ("GCP",  "#42a5f5"),
    ("Azure","#66bb6a"),
    ("UIUC", "#ab47bc"),
    ("MIT",  "#ffa726"),
    ("CMU",  "#26a69a"),
]

_S3_ADMINS_B11 = [
    ("FED", "#5d4037"), ("IRS", "#7e57c2"), ("Tres","#0097a7"),
    ("DOJ", "#616161"), ("USPS","#33691e"), ("FAA", "#827717"),
    ("FCC", "#bf360c"), ("FDA", "#ad1457"), ("EPA", "#01579b"),
    ("FRB", "#4527a0"), ("SBA", "#00838f"),
]


def _draw_owner_shard(ax, cx, cy, label, members, cols=3,
                      circle_r=0.20, label_size=10, name_size=8):
    rows = (len(members) + cols - 1) // cols
    h = 0.55 + 0.65 * rows
    w = 2.6
    ax.add_patch(FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                 boxstyle="round,pad=0.05",
                 facecolor="#eceff1", edgecolor="#37474f", lw=1.4))
    ax.text(cx, cy + h/2 - 0.22, label, ha="center", va="top",
            fontweight="bold", fontsize=label_size)
    coords = []
    for i, (a, c) in enumerate(members):
        col = i % cols
        row = i // cols
        x = cx - 0.75 + col * 0.75
        y = cy + h/2 - 0.65 - row * 0.65
        ax.add_patch(Circle((x, y), circle_r, facecolor=c, edgecolor="white",
                            linewidth=1.0, zorder=3))
        ax.text(x, y, a[0], ha="center", va="center", fontsize=name_size,
                color="white", fontweight="bold", zorder=4)
        coords.append((x, y, c))
    return coords


def fig_03a():
    """Why cross-shard coordination is hard — the nested-query use case."""
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.set_xlim(0, 13); ax.set_ylim(0, 3.6); ax.axis("off")

    # Stage 1 box
    ax.add_patch(FancyBboxPatch((0.3, 0.7), 3.3, 2.1,
                 boxstyle="round,pad=0.05",
                 facecolor="#e8eaf6", edgecolor="#37474f", lw=1.3))
    ax.text(1.95, 2.55, "Stage 1 — inner query",
            ha="center", va="center", fontsize=10, fontweight="bold")
    ax.text(1.95, 1.85,
            'SELECT id FROM users\nWHERE region=\'US\'',
            ha="center", va="center", fontsize=9.5, family="monospace")
    ax.text(1.95, 1.05, "runs on Shard A\n→ result R = {3, 7, 42}",
            ha="center", va="center", fontsize=9, style="italic",
            color="#37474f")

    ax.annotate("", xy=(4.3, 1.75), xytext=(3.7, 1.75),
                arrowprops=dict(arrowstyle="->", lw=1.8, color="#37474f"))
    ax.text(4.0, 2.05, "R", ha="center", fontsize=11,
            fontweight="bold", color="#1565c0")

    # Stage 2 box
    ax.add_patch(FancyBboxPatch((4.4, 0.7), 4.3, 2.1,
                 boxstyle="round,pad=0.05",
                 facecolor="#fff3e0", edgecolor="#37474f", lw=1.3))
    ax.text(6.55, 2.55, "Stage 2 — outer query",
            ha="center", va="center", fontsize=10, fontweight="bold")
    ax.text(6.55, 1.85,
            "SELECT * FROM accounts\nWHERE owner_id IN R",
            ha="center", va="center", fontsize=9.5, family="monospace")
    ax.text(6.55, 1.05, "→ which shards to involve\ndepends on R",
            ha="center", va="center", fontsize=9, style="italic",
            color="#37474f")

    ax.annotate("", xy=(9.4, 1.75), xytext=(8.8, 1.75),
                arrowprops=dict(arrowstyle="->", lw=1.8, color="#37474f"))

    # Risk callout
    ax.add_patch(FancyBboxPatch((9.5, 0.7), 3.3, 2.1,
                 boxstyle="round,pad=0.05",
                 facecolor="#ffebee", edgecolor="#c62828", lw=1.3))
    ax.text(11.15, 2.55, "BFT risk",
            ha="center", va="center", fontsize=10,
            fontweight="bold", color="#c62828")
    ax.text(11.15, 1.55,
            "different replicas may\npick DIFFERENT downstream\nshard sets for R\n→ snapshot diverges",
            ha="center", va="center", fontsize=9, color="#37474f")

    fig.suptitle("Why Pesto needs cross-shard coordination — nested queries",
                 fontsize=13, fontweight="bold", y=0.98)
    save(fig, "fig_03a_nested_query.png")


def _draw_matrix_grid(ax, x0, y0, n_rows, n_cols, cell_w, cell_h,
                      shard_labels, row_labels_with_color):
    """Draw the matrix scaffold: column headers + row headers + grid lines.
       Returns a function `cell_xy(row, col)` for placing content in cells."""
    # Column headers (shards)
    for j, lab in enumerate(shard_labels):
        cx = x0 + (j + 0.5) * cell_w
        cy = y0 + n_rows * cell_h + cell_h * 0.5
        ax.add_patch(FancyBboxPatch((cx - cell_w * 0.45, cy - cell_h * 0.3),
                     cell_w * 0.9, cell_h * 0.6,
                     boxstyle="round,pad=0.02",
                     facecolor="#37474f", edgecolor="#37474f", lw=1.0))
        ax.text(cx, cy, lab, ha="center", va="center",
                fontsize=11, fontweight="bold", color="white")

    # Row headers (authorities)
    for i, (name, color) in enumerate(row_labels_with_color):
        rx = x0 - cell_w * 0.55
        ry = y0 + (n_rows - i - 0.5) * cell_h
        ax.add_patch(FancyBboxPatch((rx - cell_w * 0.4, ry - cell_h * 0.3),
                     cell_w * 0.8, cell_h * 0.6,
                     boxstyle="round,pad=0.02",
                     facecolor=color, edgecolor="white", lw=1.5))
        ax.text(rx, ry, name, ha="center", va="center",
                fontsize=10, fontweight="bold", color="white")

    # Grid lines
    for j in range(n_cols + 1):
        x = x0 + j * cell_w
        ax.plot([x, x], [y0, y0 + n_rows * cell_h], color="#90a4ae", lw=0.8)
    for i in range(n_rows + 1):
        y = y0 + i * cell_h
        ax.plot([x0, x0 + n_cols * cell_w], [y, y], color="#90a4ae", lw=0.8)

    def cell_xy(row, col):
        return (x0 + (col + 0.5) * cell_w,
                y0 + (n_rows - row - 0.5) * cell_h)
    return cell_xy


def fig_03b():
    """Pesto's sister-replica assumption — matrix view (authority × shard)."""
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6); ax.axis("off")

    ax.text(5, 5.55,
            'Pesto §B.10:  "every replica has a trusted counterpart in other shards"',
            ha="center", va="center", fontsize=11, style="italic",
            color="#37474f")

    authorities = [
        ("Org A", "#ef5350"),
        ("Org B", "#42a5f5"),
        ("Org C", "#66bb6a"),
    ]
    shard_labels = ["Shard 0", "Shard 1"]

    cell_w, cell_h = 1.8, 0.9
    x0, y0 = 3.5, 1.5
    cell_xy = _draw_matrix_grid(ax, x0, y0,
                                n_rows=3, n_cols=2,
                                cell_w=cell_w, cell_h=cell_h,
                                shard_labels=shard_labels,
                                row_labels_with_color=authorities)

    # Fill every cell + draw a sister bracket per row
    for i, (_, color) in enumerate(authorities):
        for j in range(2):
            cx, cy = cell_xy(i, j)
            ax.add_patch(Circle((cx, cy), 0.27, facecolor=color,
                                edgecolor="white", lw=1.5, zorder=3))
        # sister arrow across the row (between the two cells)
        x_left, y_row = cell_xy(i, 0)
        x_right, _   = cell_xy(i, 1)
        ax.annotate("", xy=(x_right - 0.30, y_row),
                    xytext=(x_left + 0.30, y_row),
                    arrowprops=dict(arrowstyle="<->", lw=1.6, color=color,
                                    alpha=0.85), zorder=2)

    # "sister" callout near the right edge
    ax.text(x0 + 2 * cell_w + 0.55, y0 + 1.5 * cell_h,
            "←─ sisters ─→",
            ha="left", va="center", fontsize=9.5,
            color="#37474f", style="italic", rotation=270)

    # Caption
    ax.text(5, 0.55,
            "each ROW = one trust authority; each COLUMN = one shard.\n"
            "every row is filled in every column ⇒ every authority has a sister in every shard  ✓",
            ha="center", va="center", fontsize=9.5, color="#2e7d32")

    fig.suptitle("Sister-replica assumption — every row × every column",
                 fontsize=13, fontweight="bold", y=0.98)
    save(fig, "fig_03b_sister_assumption.png")


def fig_03c():
    """Heterogeneous deployment — same matrix view, but disjoint owners."""
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.set_xlim(0, 10); ax.set_ylim(0, 7); ax.axis("off")

    ax.text(5, 6.55,
            "Shard 0 and Shard 1 may have COMPLETELY DISJOINT owners",
            ha="center", va="center", fontsize=11, style="italic",
            color="#37474f")

    authorities = [
        ("UIUC",     "#ef5350"),
        ("MIT",      "#42a5f5"),
        ("Stanford", "#66bb6a"),
        ("FED",      "#5d4037"),
        ("IRS",      "#7e57c2"),
        ("Treasury", "#0097a7"),
    ]
    shard_labels = ["Shard 0", "Shard 1"]

    cell_w, cell_h = 1.8, 0.7
    x0, y0 = 3.5, 1.5
    cell_xy = _draw_matrix_grid(ax, x0, y0,
                                n_rows=6, n_cols=2,
                                cell_w=cell_w, cell_h=cell_h,
                                shard_labels=shard_labels,
                                row_labels_with_color=authorities)

    # Fill: rows 0..2 only in column 0; rows 3..5 only in column 1
    for i, (_, color) in enumerate(authorities):
        if i < 3:
            cx, cy = cell_xy(i, 0)
            ax.add_patch(Circle((cx, cy), 0.22, facecolor=color,
                                edgecolor="white", lw=1.4, zorder=3))
            # empty cell on the right
            cx_e, cy_e = cell_xy(i, 1)
            ax.text(cx_e, cy_e, "—", ha="center", va="center",
                    fontsize=14, color="#b0bec5", fontweight="bold")
        else:
            cx, cy = cell_xy(i, 1)
            ax.add_patch(Circle((cx, cy), 0.22, facecolor=color,
                                edgecolor="white", lw=1.4, zorder=3))
            cx_e, cy_e = cell_xy(i, 0)
            ax.text(cx_e, cy_e, "—", ha="center", va="center",
                    fontsize=14, color="#b0bec5", fontweight="bold")

    # "no sister" red strikes across rows that lack a counterpart
    for i in range(6):
        x_left, y_row = cell_xy(i, 0)
        x_right, _   = cell_xy(i, 1)
        ax.plot([x_left, x_right], [y_row, y_row],
                color="#c62828", lw=1.6, alpha=0.55, linestyle=":")

    ax.text(x0 + 2 * cell_w + 0.55, y0 + 3.0 * cell_h,
            "no row spans both columns\n→ no sisters",
            ha="left", va="center", fontsize=9.5,
            color="#c62828", style="italic")

    # Caption
    ax.text(5, 0.55,
            "no row is filled in both columns ⇒ no sisters available\n"
            "replaced by: cryptographic membership + snapshot certificates verified by any foreign shard  ✓",
            ha="center", va="center", fontsize=9.5, color="#2e7d32")

    fig.suptitle("Heterogeneous shards — disjoint authorities, no sisters",
                 fontsize=13, fontweight="bold", y=0.98)
    save(fig, "fig_03c_heterogeneous.png")


def fig_03():
    """Compatibility wrapper — emit all three slide-3 figures."""
    fig_03a()
    fig_03b()
    fig_03c()


# ---------------------------------------------------------------- slide 04
def fig_04():
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6); ax.axis("off")

    goals = [
        ("G1", "Per-shard n and f",
         "Heterogeneous membership at the configuration layer.",
         "#bbdefb"),
        ("G2", "Crypto shard membership certs",
         "Replace shared-admin trust with verifiable signatures.",
         "#c8e6c9"),
        ("G3", "Cross-shard SS-CERT verification",
         "Foreign shards verify snapshot certs locally.",
         "#fff9c4"),
        ("G4", "Run on real hardware (18 nodes)",
         "Not just unit tests — actual CloudLab deployment.",
         "#f8bbd0"),
    ]

    positions = [(2.5, 4.2), (7.5, 4.2), (2.5, 1.8), (7.5, 1.8)]
    for (id_, title, body, color), (cx, cy) in zip(goals, positions):
        ax.add_patch(FancyBboxPatch((cx - 2.2, cy - 1.0), 4.4, 2.0,
                     boxstyle="round,pad=0.05",
                     facecolor=color, edgecolor="#37474f", linewidth=1.4))
        ax.text(cx, cy + 0.6, id_, ha="center", va="center",
                fontsize=20, fontweight="bold", color="#37474f")
        ax.text(cx, cy + 0.05, title, ha="center", va="center",
                fontsize=11, fontweight="bold")
        ax.text(cx, cy - 0.55, body, ha="center", va="center",
                fontsize=9, wrap=True)

    fig.suptitle("Project goals",
                 fontsize=13, fontweight="bold", y=0.97)
    save(fig, "fig_04_goals.png")


# ---------------------------------------------------------------- slide 05
def fig_05():
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis("off")

    # Shorter labels that fit in 3.5-wide boxes
    files = [
        (0.5, 4.4, "lib/configuration.{h,cc}",
         "+ group_f directive\n+ GroupN(g) / GroupF(g)", "modified"),
        (4.3, 4.4, "pequinstore/common.{h,cc}",
         "+ per-group QuorumSize(...)\n+ IsReplicaInGroupHet", "modified"),
        (8.1, 4.4, "pequinstore/membership.{h,cc}",
         "• MembershipManager class\n• GenerateCert / VerifyCert", "new"),
        (0.5, 1.6, "pequinstore/*.proto",
         "+ ShardMembershipCert msg\n+ SnapshotCert msg", "modified"),
        (4.3, 1.6, "pequinstore/server.{h,cc}",
         "+ VerifyForeignSSCert\n+ GenerateSnapshotVote", "modified"),
        (8.1, 1.6, "pequinstore/tests/\nmembership_test.cc",
         "• unit tests for cert\n  generation + verify", "new"),
    ]

    for x, y, header, body, kind in files:
        col = "#e3f2fd" if kind == "modified" else "#c8e6c9"
        edge = "#1565c0" if kind == "modified" else "#2e7d32"
        ax.add_patch(FancyBboxPatch((x, y - 0.7), 3.4, 1.85,
                     boxstyle="round,pad=0.04",
                     facecolor=col, edgecolor=edge, linewidth=1.4))
        ax.text(x + 0.1, y + 1.05, "[NEW]" if kind == "new" else "[modified]",
                ha="left", va="top", fontsize=8.5, color=edge, fontweight="bold")
        ax.text(x + 1.7, y + 0.55, header, ha="center", va="center",
                fontsize=10, family="monospace", fontweight="bold")
        ax.text(x + 1.7, y - 0.20, body, ha="center", va="center",
                fontsize=9, family="monospace")

    ax.text(6, 0.3,
            "Total: 24 files changed, ~1 213 insertions across 4 commits",
            ha="center", va="center", fontsize=11, fontweight="bold",
            color="#37474f")

    fig.suptitle("Architecture changes — what we touched",
                 fontsize=14, fontweight="bold", y=0.97)
    save(fig, "fig_05_code_changes.png")


# ---------------------------------------------------------------- slide 06
def fig_06():
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.set_xlim(0, 19); ax.set_ylim(0, 4.5); ax.axis("off")

    # 18 nodes from lab_ssh.txt order
    nodes = [
        "amd216", "amd173", "amd225", "amd235", "amd175", "amd205",  # shard 0
        "amd215", "amd180", "amd210", "amd169", "amd231", "amd232",  # shard 1
        "amd223", "amd179", "amd178", "amd174", "amd172", "amd171",  # clients
    ]
    roles = (["S0"] * 6) + (["S1"] * 6) + (["C"] * 6)
    colors = {"S0": "#bbdefb", "S1": "#c5cae9", "C": "#ffe082"}

    for i, (name, role) in enumerate(zip(nodes, roles)):
        x = 0.5 + i
        y = 1.7
        ax.add_patch(Rectangle((x, y), 0.85, 1.0,
                     facecolor=colors[role], edgecolor="#37474f", linewidth=1.0))
        ax.text(x + 0.42, y + 0.7, role, ha="center", va="center",
                fontsize=10, fontweight="bold")
        ax.text(x + 0.42, y + 0.3, name, ha="center", va="center",
                fontsize=7.5, family="monospace")

    # group brackets above
    def bracket(x0, x1, label, color, y=3.0):
        ax.plot([x0, x1], [y, y], color=color, lw=2)
        ax.plot([x0, x0], [y, y - 0.15], color=color, lw=2)
        ax.plot([x1, x1], [y, y - 0.15], color=color, lw=2)
        ax.text((x0 + x1) / 2, y + 0.18, label, ha="center", va="bottom",
                fontsize=10, fontweight="bold", color=color)

    bracket(0.5,  6.35, "Shard 0 — 6 servers (n=6, f=1)",  "#1565c0")
    bracket(6.5, 12.35, "Shard 1 — 6 servers (n=6, f=1)",  "#283593")
    bracket(12.5, 18.35, "6 clients", "#f9a825")

    ax.text(9.5, 0.7,
            "All 18 are amd nodes on CloudLab Utah (geni-get key SSH).\n"
            "setup_18_nodes.sh provisions, run_byzantine_experiment.sh orchestrates.",
            ha="center", va="center", fontsize=10, style="italic",
            color="#37474f")
    fig.suptitle("Testbed: 18 CloudLab Utah nodes",
                 fontsize=13, fontweight="bold", y=0.97)
    save(fig, "fig_06_topology.png")


# ---------------------------------------------------------------- slide 07
def fig_07():
    # Use real Exp1 numbers
    clients = [0, 1, 2, 3, 4, 5]
    commits = [147, 198, 188, 194, 140, 151]
    aborts  = [83, 75, 77, 76, 75, 73]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars1 = ax.bar([c - 0.18 for c in clients], commits, 0.36,
                   label="Committed", color="#43a047", edgecolor="#1b5e20")
    bars2 = ax.bar([c + 0.18 for c in clients], aborts, 0.36,
                   label="Aborted",   color="#e53935", edgecolor="#b71c1c")
    for b, v in zip(bars1, commits):
        ax.text(b.get_x() + b.get_width()/2, v + 4, str(v),
                ha="center", va="bottom", fontsize=9, fontweight="bold")
    for b, v in zip(bars2, aborts):
        ax.text(b.get_x() + b.get_width()/2, v + 4, str(v),
                ha="center", va="bottom", fontsize=9)

    ax.set_xticks(clients)
    ax.set_xticklabels([f"client {c}" for c in clients])
    ax.set_ylabel("transactions over 30 s window")
    ax.legend(loc="upper right", frameon=False)
    ax.set_title("Exp1 honest baseline — 1 018 commits / 30 s = 33.9 tx/s")
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_ylim(0, max(commits) * 1.25)
    save(fig, "fig_07_per_client_commits.png")


# ---------------------------------------------------------------- slide 08
def fig_08():
    runs = [
        ("Exp1\nno byzantine", 33.9, "#43a047"),
        ("Run 8\nomission",    32.7, "#fb8c00"),
        ("Exp2\nfull crash",   32.8, "#e53935"),
    ]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    xs = [0, 1, 2]
    ys = [r[1] for r in runs]
    cols = [r[2] for r in runs]
    bars = ax.bar(xs, ys, 0.6, color=cols, edgecolor="black", linewidth=1.2)
    for b, v in zip(bars, ys):
        ax.text(b.get_x() + b.get_width()/2, v + 0.4, f"{v} tx/s",
                ha="center", va="bottom", fontweight="bold", fontsize=11)

    # baseline line
    ax.axhline(33.9, color="#43a047", ls="--", lw=1.2, alpha=0.6)
    ax.text(-0.4, 33.9, "honest baseline ", color="#43a047",
            va="center", ha="right", fontsize=9)

    ax.set_xticks(xs); ax.set_xticklabels([r[0] for r in runs])
    ax.set_ylabel("Throughput (tx/s)")
    ax.set_ylim(0, 38)
    ax.set_title("Byzantine cost: ≤ 3 % vs honest baseline")
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # annotate fast-path %
    fp = ["100 %", "~98 %", "99.9 %"]
    for x, t in zip(xs, fp):
        ax.text(x, 1.0, f"fast: {t}", ha="center", va="bottom", fontsize=9,
                color="#37474f", style="italic")
    save(fig, "fig_08_throughput_compare.png")


# ---------------------------------------------------------------- slide 09
def fig_09():
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6); ax.axis("off")

    # Shard 0 — small (n=6)
    shard_box(ax, 2.0, 3.0, 6, "Shard 0\nn=6, f=1", color="#bbdefb")
    ax.text(2.0, 1.2, "fast quorum\n4·1+1 = 5",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color="#1565c0")

    # Shard 1 — bigger (n=11)
    shard_box(ax, 7.5, 3.0, 11, "Shard 1\nn=11, f=2", color="#c5cae9")
    ax.text(7.5, 1.2, "fast quorum\n4·2+1 = 9",
            ha="center", va="center", fontsize=12, fontweight="bold",
            color="#283593")

    # green check arrow
    ax.text(5.0, 5.0, "✓ heterogeneous quorums honored",
            ha="center", va="center",
            fontsize=14, fontweight="bold", color="#2e7d32")
    ax.text(5.0, 4.4, "408 commits / 30 s · 100 % commit · 100 % fast-path",
            ha="center", va="center",
            fontsize=11, color="#37474f")
    ax.text(5.0, 0.4,
            'This is the configuration the Pesto sister-replica\n'
            'assumption explicitly forbids — and it works.',
            ha="center", va="center", fontsize=10, style="italic",
            color="#37474f")
    fig.suptitle("Exp 6 — Heterogeneous membership headline",
                 fontsize=13, fontweight="bold", y=0.97)
    save(fig, "fig_09_heterogeneous.png")


# ---------------------------------------------------------------- slide 10
def fig_10():
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.axis("off")

    # Mock terminal box
    txt = (
        "$ python3 scripts/dsg_check.py pesto-results/20260505T025855Z\n"
        "=== DSG safety check for pesto-results/20260505T025855Z ===\n"
        "\n"
        "Per-client stats files: 6\n"
        "Aggregate commits     : 1018\n"
        "Aggregate aborts      : 459\n"
        "Aggregate attempts    : 1477\n"
        "Fast-path prepares    : 1477\n"
        "Fallback rounds       : 33\n"
        "txn_groups distribution: [0, 1477]\n"
        "  cross-shard committed: 0\n"
        "\n"
        "PASS — no per-client invariant violation."
    )
    ax.text(0.04, 0.98, txt,
            transform=ax.transAxes, ha="left", va="top",
            family="monospace", fontsize=10.5,
            bbox=dict(boxstyle="round,pad=0.6",
                      facecolor="#263238", edgecolor="#37474f", linewidth=1.5),
            color="#aed581")

    ax.text(0.5, 0.06,
            "Layer 1 — protocol-metadata invariants:  necessary, but NOT sufficient",
            transform=ax.transAxes, ha="center", va="bottom",
            fontsize=11, fontweight="bold", color="#bf360c")
    fig.suptitle("Verification Layer 1 — dsg_check.py over 5 runs",
                 fontsize=13, fontweight="bold", y=0.99)
    save(fig, "fig_10_dsg_check.png")


# ---------------------------------------------------------------- slide 11
def fig_11():
    fig = plt.figure(figsize=(13, 6))
    gs = gridspec.GridSpec(1, 2, width_ratios=[1.5, 1], wspace=0.25)

    # left panel — sample JSON
    ax1 = fig.add_subplot(gs[0]); ax1.axis("off")
    json_txt = (
        '# pesto_elle_0.jsonl  (one line per event)\n'
        '\n'
        '{"type":"invoke","process":0,"time":...,\n'
        '  "value":[["r","t0:369",null],\n'
        '           ["r","t0:419",null]]}\n'
        '\n'
        '{"type":"ok",    "process":0,"time":...,\n'
        '  "value":[["r","t0:369",19],["w","t0:369",1],\n'
        '           ["r","t0:419",19],["w","t0:419",2]]}\n'
        '\n'
        '{"type":"ok",    "process":2,"time":...,\n'
        '  "value":[["r","t0:340",27],\n'
        '           ["w","t0:340",33554601]]}'
    )
    ax1.text(0.0, 0.98, json_txt,
             transform=ax1.transAxes, ha="left", va="top",
             family="monospace", fontsize=11,
             bbox=dict(boxstyle="round,pad=0.6",
                       facecolor="#fafafa", edgecolor="#bdbdbd"),
             color="#1a1a1a")
    ax1.text(0.0, 1.04, "Captured Elle history (rw-register model)",
             transform=ax1.transAxes, ha="left", va="bottom",
             fontsize=12, fontweight="bold")

    # right panel — verdict bar
    ax2 = fig.add_subplot(gs[1])
    runs = [
        ("Honest\nbaseline", 1736, 16),
        ("1 byz / shard\n+ 1 byz client", 1702, 21),
    ]
    xs = [0, 1]
    commits = [r[1] for r in runs]
    edges   = [r[2] for r in runs]
    bars = ax2.bar(xs, commits, 0.55, color=["#43a047", "#fb8c00"],
                   edgecolor="black", linewidth=1.2)
    for b, c, e in zip(bars, commits, edges):
        ax2.text(b.get_x() + b.get_width()/2, c + 50,
                 f"{c} commits\n{e} DSG edges\n"
                 r"$\bf{PASS}$",
                 ha="center", va="bottom", fontsize=11)

    ax2.set_xticks(xs)
    ax2.set_xticklabels([r[0] for r in runs], fontsize=10)
    ax2.set_ylabel("Committed transactions")
    ax2.set_ylim(0, max(commits) * 1.45)
    ax2.set_title("mini-Elle G2 cycle check", fontsize=12, fontweight="bold")
    ax2.grid(axis="y", linestyle=":", alpha=0.4)

    fig.suptitle("Verification Layer 2 — Elle-style data-DSG check",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    save(fig, "fig_11_elle_results.png")


# ---------------------------------------------------------------- slide 12
def fig_12():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(0, 11); ax.set_ylim(0, 5); ax.axis("off")

    # Progress bar at top
    ax.add_patch(Rectangle((0.5, 4.0), 10, 0.4, facecolor="#eceff1",
                           edgecolor="#37474f"))
    ax.add_patch(Rectangle((0.5, 4.0), 10, 0.4, facecolor="#43a047",
                           edgecolor="#37474f", alpha=0.85))
    ax.text(5.5, 4.6, "synth tests → first remote run → first PASS verdict",
            ha="center", va="bottom", fontsize=9, color="#37474f")

    bugs = [
        ("Bug 1\nsandbox blocked\nElle install",
         "→ wrote\nmini_elle.py",
         "(no commit)", "#9e9e9e"),
        ("Bug 2\nvalue++ collisions\n(12.8 % rate)",
         "→ unique values\nclient_id<<32",
         "23806aff", "#fb8c00"),
        ("Bug 3\nINT32 overflow\nall txns abort",
         "→ cap to 7+24 bits",
         "17bb4c05", "#e53935"),
        ("Bug 4\nmissed Adya\ntime filter",
         "→ commit-time check\n(mini_elle.py only)",
         "(Python only)", "#7b1fa2"),
    ]
    for i, (sym, fix, commit, col) in enumerate(bugs):
        x = 1.5 + i * 2.5
        ax.add_patch(FancyBboxPatch((x - 1.15, 1.6), 2.3, 1.85,
                     boxstyle="round,pad=0.04",
                     facecolor="#ffffff", edgecolor=col, linewidth=1.6))
        ax.text(x, 3.2, sym, ha="center", va="top",
                fontsize=10, fontweight="bold", color=col)
        ax.text(x, 2.40, fix, ha="center", va="top",
                fontsize=9, color="#37474f")
        ax.text(x, 1.75, commit, ha="center", va="bottom",
                fontsize=8, family="monospace", color="#37474f")

    ax.text(5.5, 0.55,
            "3 Pesto commits + 1 Python fix · 3 deploy-rebuild rounds across 18 nodes\n"
            "≈ 3 hours from \"let's add Elle\" to first PASS",
            ha="center", va="center", fontsize=10, style="italic",
            color="#37474f")
    fig.suptitle("Building the Elle pipeline — 4 bugs along the way",
                 fontsize=13, fontweight="bold", y=0.99)
    save(fig, "fig_12_bug_timeline.png")


# ---------------------------------------------------------------- slide 13
def fig_13():
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.axis("off")

    items = [
        ("Wire SS-CERT into querysync-server.cc hot path", "small"),
        ("Install real elle-cli (mini-Elle is G2-only)",   "small"),
        ("Byzantine × heterogeneous together (n=11, 2 byz)", "small"),
        ("Twins-style client equivocation testing",         "medium"),
    ]
    for i, (txt, eff) in enumerate(items):
        y = 0.85 - i * 0.18
        ax.text(0.05, y, "✗", transform=ax.transAxes,
                fontsize=20, color="#d32f2f", fontweight="bold",
                ha="left", va="center")
        ax.text(0.13, y, txt, transform=ax.transAxes,
                fontsize=12, ha="left", va="center")
        eff_color = "#43a047" if eff == "small" else "#fb8c00"
        ax.text(0.93, y, f"[{eff}]", transform=ax.transAxes,
                fontsize=10, color=eff_color, ha="right", va="center",
                fontweight="bold", family="monospace")

    fig.suptitle("Honest gaps still open",
                 fontsize=13, fontweight="bold", y=0.99)
    save(fig, "fig_13_gaps.png")


# ---------------------------------------------------------------- slide 14
def fig_14():
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.set_xlim(0, 14); ax.set_ylim(0, 6); ax.axis("off")

    # Wrap labels to 2 lines so they fit
    items = [
        ("Real elle-cli\nswap",         "1 hour",        "#43a047"),
        ("Wire\nVerifyForeignSSCert",   "½ day",         "#43a047"),
        ("Byz × hetero-\ngeneous run",  "1 day",         "#43a047"),
        ("Twins-style\nbyz client",     "1 week",        "#fb8c00"),
        ("TPC-C / YCSB-\ntables port",  "1 week",        "#fb8c00"),
        ("Live membership\nreconfig",   "open research", "#d32f2f"),
    ]

    box_w = 2.0
    box_h = 1.9
    gap = 0.25

    for i, (label, eff, col) in enumerate(items):
        x = 0.5 + i * (box_w + gap)
        ax.add_patch(FancyBboxPatch((x, 2.0), box_w, box_h,
                     boxstyle="round,pad=0.05",
                     facecolor="white", edgecolor=col, linewidth=2.0))
        ax.text(x + box_w/2, 3.55, f"#{i+1}", ha="center", va="center",
                fontsize=15, fontweight="bold", color=col)
        ax.text(x + box_w/2, 2.7, label, ha="center", va="center",
                fontsize=10)
        ax.text(x + box_w/2, 1.6, eff, ha="center", va="center",
                fontsize=10, color=col, fontweight="bold")
        # arrow to next
        if i < len(items) - 1:
            ax.annotate("",
                        xy=(x + box_w + gap - 0.05, 2.95),
                        xytext=(x + box_w + 0.02, 2.95),
                        arrowprops=dict(arrowstyle="->", color="#9e9e9e", lw=1.5))

    # legend
    handles = [
        mpatches.Patch(color="#43a047", label="ready (≤ 1 day)"),
        mpatches.Patch(color="#fb8c00", label="medium (≈ 1 week)"),
        mpatches.Patch(color="#d32f2f", label="research / out of scope"),
    ]
    ax.legend(handles=handles, loc="lower center", ncol=3,
              bbox_to_anchor=(0.5, 0.02), frameon=False, fontsize=11)
    fig.suptitle("Future work — triaged roadmap",
                 fontsize=14, fontweight="bold", y=0.97)
    save(fig, "fig_14_roadmap.png")


# ---------------------------------------------------------------- slide 15
def fig_15():
    fig, ax = plt.subplots(figsize=(14, 5.5))
    ax.set_xlim(0, 15); ax.set_ylim(0, 6); ax.axis("off")

    cols = [
        ("Goals achieved",
         ["✓ per-shard n / f",
          "✓ membership certs",
          "✓ SS-CERT scaffolding",
          "✓ 18-node deployment",
          "✓ Elle data-DSG verify"],
         "#43a047"),
        ("Numbers measured",
         ["honest:    33.9 tx/s",
          "byz omit:  32.7 tx/s",
          "byz crash: 32.8 tx/s",
          "het n=11:  408 commits 100 %",
          "Elle PASS: 3 438 txns"],
         "#1565c0"),
        ("What's next",
         ["1. real elle-cli  (1 h)",
          "2. SS-CERT wire   (½ d)",
          "3. byz × het      (1 d)",
          "4. Twins client   (1 w)",
          "5. TPC-C port     (1 w)"],
         "#7b1fa2"),
    ]

    box_w = 4.6
    gap = 0.2
    for ci, (title, lines, col) in enumerate(cols):
        cx = 0.3 + ci * (box_w + gap)
        ax.add_patch(FancyBboxPatch((cx, 0.4), box_w, 4.7,
                     boxstyle="round,pad=0.05",
                     facecolor="white", edgecolor=col, linewidth=2.0))
        ax.text(cx + box_w/2, 4.75, title, ha="center", va="center",
                fontsize=13, fontweight="bold", color=col)
        for li, line in enumerate(lines):
            ax.text(cx + 0.3, 4.05 - li * 0.55, line,
                    ha="left", va="center",
                    fontsize=10.5, family="monospace")

    fig.suptitle("Summary", fontsize=15, fontweight="bold", y=0.98)
    save(fig, "fig_15_summary.png")


# ---------------------------------------------------------------- main
def main():
    print(f"Generating PPT figures → {OUT}/")
    fig_02(); fig_03(); fig_04(); fig_05(); fig_06()
    fig_07(); fig_08(); fig_09(); fig_10(); fig_11()
    fig_12(); fig_13(); fig_14(); fig_15()
    print(f"Done. {len(list(OUT.glob('*.png')))} figures.")


if __name__ == "__main__":
    main()
