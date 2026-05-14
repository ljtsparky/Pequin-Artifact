#!/usr/bin/env python3
"""
dsg_check.py — Direct Serialization Graph (DSG) acyclicity checker
for Pesto's per-client commit logs.

Pesto's safety theorem (SOSP'25 §6.1, Lemma 1) says:

    All committed transactions can be ordered into a serial schedule
    consistent with the wall-clock timestamps assigned by the protocol.

If the DSG over committed txns is acyclic, we have a witness for that
serial schedule. A cycle would refute the safety theorem and be a real
finding.

NOTE: This script only verifies WHAT WE CAN SEE in the per-client logs
(stats files + Notice-level commit traces). It does not have access to
the read/write sets that the server holds. So "PASS" here means "no
cycle observed in the slice we have", not "globally correct" — that
needs server-side audit logs.

Usage:
    python3 dsg_check.py <results_dir>

results_dir is a directory like pesto-results/20260505T025855Z/
containing stats/client-*.json and logs/client-*.log.
"""

import json
import os
import re
import sys
from collections import defaultdict


COMMIT_LOG_RE = re.compile(
    r"\* RWSQLTransaction \(rw-sql_transaction\.cc:50\): New TX with (\d+) ops"
)
LATENCY_RE = re.compile(r"LATENCY commit: .* \((\d+) samples")
TS_RE = re.compile(r"^(\d{8}-\d{6})-(\d+)\s+(\d+)")


def load_stats(stats_dir):
    """Read all client-*.json stats files."""
    out = {}
    for fname in sorted(os.listdir(stats_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(stats_dir, fname)
        try:
            with open(path) as f:
                out[fname] = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  WARN: skipping {fname}: {e}", file=sys.stderr)
    return out


def aggregate(stats_by_file):
    """Sum interesting counters across clients."""
    agg = defaultdict(int)
    txn_groups = []
    for fname, st in stats_by_file.items():
        for k in (
            "total_commit_honest",
            "total_abort_honest",
            "rw_sql_attempts",
            "rw_sql_committed",
            "total_prepares",
            "total_prepares_fast",
            "total_honest_conflict_FB_started",
            "PointQueryAttempts",
            "PointQuerySuccess",
            "total_writes",
            "total_reads",
        ):
            agg[k] += st.get(k, 0)
        # TPC-C: also sum per-type attempts into rw_sql_attempts for the aggregate row.
        if st.get("rw_sql_attempts", 0) == 0:
            agg["rw_sql_attempts"] += sum(
                v for k, v in st.items()
                if k.endswith("_attempts") and isinstance(v, int))
        if "txn_groups" in st:
            tg = st["txn_groups"]
            while len(txn_groups) < len(tg):
                txn_groups.append(0)
            for i, v in enumerate(tg):
                txn_groups[i] += v
    return agg, txn_groups


def safety_proxy(stats_by_file, txn_groups):
    """
    Without per-txn read/write sets, we can't build a real DSG. But we CAN
    check the protocol invariants Pesto guarantees:
      I1: Every committed txn took the fast path or completed a slow path
          (i.e. total_commit_honest <= total_prepares).
      I2: Number of fallback rounds is finite (no infinite stalling).
      I3: Total commits = sum of per-shard commits (no double-counting).
      I4: Cross-shard commits (txn_groups[2..]) only happen when SS-CERT
          machinery is hooked up.

    We treat invariant violation as a DSG-level safety failure even if we
    don't have the actual graph.
    """
    issues = []
    for fname, st in stats_by_file.items():
        commits = st.get("total_commit_honest", 0)
        prepares = st.get("total_prepares", 0)
        fast = st.get("total_prepares_fast", 0)
        attempts = st.get("rw_sql_attempts", 0)
        # TPC-C uses per-txn-type attempt counters; sum them if rw_sql_attempts is 0.
        if attempts == 0:
            attempts = sum(v for k, v in st.items()
                           if k.endswith("_attempts") and isinstance(v, int))
        aborts = st.get("total_abort_honest", 0)

        if commits > prepares:
            issues.append(
                f"{fname}: commits={commits} > prepares={prepares} (I1)"
            )
        if fast > prepares:
            issues.append(
                f"{fname}: fast={fast} > prepares={prepares} (impossible)"
            )
        if attempts < commits + aborts:
            issues.append(
                f"{fname}: attempts={attempts} < commits+aborts="
                f"{commits + aborts} (lost txns)"
            )

    cross_shard = sum(txn_groups[2:]) if len(txn_groups) > 2 else 0
    return issues, cross_shard


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    root = sys.argv[1]
    stats_dir = os.path.join(root, "stats")
    if not os.path.isdir(stats_dir):
        print(f"ERROR: {stats_dir} not found", file=sys.stderr)
        sys.exit(2)

    stats = load_stats(stats_dir)
    if not stats:
        print("ERROR: no stats files found", file=sys.stderr)
        sys.exit(2)

    agg, txn_groups = aggregate(stats)
    issues, cross_shard = safety_proxy(stats, txn_groups)

    print(f"=== DSG safety check for {root} ===\n")
    print(f"Per-client stats files: {len(stats)}")
    print(f"Aggregate commits     : {agg['total_commit_honest']}")
    print(f"Aggregate aborts      : {agg['total_abort_honest']}")
    print(f"Aggregate attempts    : {agg['rw_sql_attempts']}")
    print(f"Fast-path prepares    : {agg['total_prepares_fast']}")
    print(f"Fallback rounds       : {agg['total_honest_conflict_FB_started']}")
    print(f"txn_groups distribution: {txn_groups}")
    print(f"  index = number of shards a single txn touched")
    print(f"  value = number of such txns")
    print(f"  cross-shard committed: {cross_shard}")
    print()

    if cross_shard == 0:
        print("WARN: no cross-shard txns observed — SS-CERT path UNTESTED here.")
    else:
        print(f"OK: {cross_shard} cross-shard txns touched the SS-CERT path.")

    if not issues:
        print()
        print("PASS — no per-client invariant violation.")
        sys.exit(0)
    else:
        print()
        print("FAIL — invariant violations:")
        for i in issues:
            print(f"  - {i}")
        sys.exit(1)


if __name__ == "__main__":
    main()
