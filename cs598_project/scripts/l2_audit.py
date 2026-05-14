#!/usr/bin/env python3
"""
l2_audit.py — Cross-shard atomicity audit.

Scans every `server-g*-r*.log` file in a pesto-results run and aggregates
the `L2_AUDIT_COMMIT g=<G> r=<R> txn=<DIGEST> involved=[g0,g1,...]` lines
emitted by HandleWriteback (server.cc).

For each unique txn_digest the script computes:
  - involved_groups : the set of groups the txn CLAIMED to span (from the
    `involved=[...]` field; servers see the same Transaction proto so this
    is consistent across replicas).
  - observed_groups : the set of groups that ACTUALLY logged a commit
    line for that digest.

L2 (cross-shard atomicity) holds iff `observed_groups == involved_groups`
for every cross-shard txn.

A violation is one of:
  PARTIAL_COMMIT - involved={0,1} but observed={0}  (shard 1 dropped it)
  PHANTOM_COMMIT - involved={0}   but observed={0,1}(shard 1 spuriously committed)

Usage:
  python3 scripts/l2_audit.py pesto-results/<run-dir>

Exit code 0 on PASS, 1 on any violation, 2 on usage error.
"""
import os
import re
import sys
import glob
from collections import defaultdict

# Matches: 2026...  ... Server  (...): L2_AUDIT_COMMIT g=0 r=3 txn=abcd... involved=[0,1]
LINE_RE = re.compile(
    r"L2_AUDIT_COMMIT\s+g=(\d+)\s+r=(\d+)\s+txn=([0-9a-f]+)\s+involved=\[([0-9,\-]*)\]"
)


def parse_involved(s: str):
    if not s:
        return set()
    return set(int(x) for x in s.split(",") if x)


def scan_run(run_dir: str):
    """Return: dict txn_digest -> {
        involved: set[int],
        observed: dict[int, set[int]]   # group -> set of replica ids that logged
    }"""
    txns = defaultdict(lambda: {"involved": set(), "observed": defaultdict(set)})
    log_glob = os.path.join(run_dir, "logs", "server-g*-r*.log")
    files = sorted(glob.glob(log_glob))
    if not files:
        print(f"ERROR: no server logs at {log_glob}", file=sys.stderr)
        sys.exit(2)
    for path in files:
        try:
            with open(path, "r", errors="replace") as f:
                for line in f:
                    m = LINE_RE.search(line)
                    if not m:
                        continue
                    g = int(m.group(1))
                    r = int(m.group(2))
                    digest = m.group(3)
                    involved = parse_involved(m.group(4))
                    rec = txns[digest]
                    if involved:
                        rec["involved"] = involved
                    rec["observed"][g].add(r)
        except FileNotFoundError:
            continue
    return txns, files


def analyze(txns):
    single = 0          # involved_groups size <= 1, observed matched
    crosshard_ok = 0    # involved >= 2, observed == involved
    partial = []        # involved > observed
    phantom = []        # observed - involved non-empty
    for digest, rec in txns.items():
        inv = rec["involved"]
        obs = set(rec["observed"].keys())
        if len(inv) <= 1:
            if obs == inv:
                single += 1
            else:
                # Single-shard txn that appeared at OTHER shards — phantom
                phantom.append((digest, inv, obs))
            continue
        # Cross-shard
        if obs == inv:
            crosshard_ok += 1
        elif obs.issubset(inv) and obs != inv:
            partial.append((digest, inv, obs))
        elif not obs.issubset(inv):
            phantom.append((digest, inv, obs))
        else:
            # obs.issuperset(inv) but obs != inv — equivalent to phantom
            phantom.append((digest, inv, obs))
    return single, crosshard_ok, partial, phantom


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    run = sys.argv[1]
    print(f"=== L2 audit over {run} ===")
    txns, files = scan_run(run)
    print(f"Server logs scanned       : {len(files)}")
    print(f"Unique commit txn digests : {len(txns)}")

    single, ok, partial, phantom = analyze(txns)
    cross_seen = ok + len(partial) + len(phantom)
    print(f"Single-shard commits      : {single}")
    print(f"Cross-shard commits (OK)  : {ok}")
    print(f"PARTIAL_COMMIT violations : {len(partial)}")
    print(f"PHANTOM_COMMIT violations : {len(phantom)}")

    if partial:
        print()
        print("PARTIAL (cross-shard txn missing on some involved shard):")
        for d, inv, obs in partial[:10]:
            print(f"  {d}  involved={sorted(inv)}  observed={sorted(obs)}")
        if len(partial) > 10:
            print(f"  ... and {len(partial) - 10} more")

    if phantom:
        print()
        print("PHANTOM (txn committed on a shard NOT in its involved_groups):")
        for d, inv, obs in phantom[:10]:
            print(f"  {d}  involved={sorted(inv)}  observed={sorted(obs)}")
        if len(phantom) > 10:
            print(f"  ... and {len(phantom) - 10} more")

    print()
    if partial or phantom:
        print(f"FAIL — {len(partial)} partial + {len(phantom)} phantom")
        sys.exit(1)
    else:
        # Also flag if every cross-shard txn was observed by FEWER than the
        # expected per-shard quorum (4f+1=5 with f=1). Could mean a violation
        # that escaped because not every replica logged.
        weakly_observed = []
        for digest, rec in txns.items():
            if len(rec["involved"]) >= 2:
                for g in rec["involved"]:
                    seen_replicas = len(rec["observed"].get(g, set()))
                    if 0 < seen_replicas < 4:   # threshold heuristic
                        weakly_observed.append((digest, g, seen_replicas))
                        break
        if weakly_observed:
            print(f"NOTE: {len(weakly_observed)} cross-shard txns observed by < 4 replicas on some shard")
            print("      (may indicate replica-level lag rather than safety violation)")
        print("PASS — every cross-shard commit landed on every involved shard.")
        sys.exit(0)


if __name__ == "__main__":
    main()
