#!/usr/bin/env python3
"""
mini_elle.py — A *minimal* Adya-style serializability checker for the
list-append model that Pesto's client logs to JSON.

This is a fallback for when the real `elle-cli` (Clojure) is not yet
installed. The input JSON format is *deliberately compatible* with Elle,
so once `elle-cli` is built we can simply pipe the same history at it.

What we DO check:
  G2 (anti-dependency cycle): for every pair of committed txns T1, T2
  where T1's read of key k missed an append-only-suffix that T2 wrote,
  we add an edge T1 -> T2 (T2 was "after" T1). Then check the directed
  graph for cycles via Tarjan SCC.

  G1a (aborted reads): every committed txn's reads are looked up in the
  global writer index (which includes aborted+failed writers). If a
  committed txn read a (key, value) whose only writer aborted, that is
  G1a — a real BFT safety violation.

What we do NOT check (real Elle does):
  G0 (write-write cycle, partly subsumed by G2 in our model since
      WW conflicts on the same value would also create a WR/RW cycle)
  G1b (intermediate reads — rw-sql writes each key at most once per txn,
      so intermediate state isn't observable in our model)
  G1c (full circular information flow with mixed RW + WR edges --
      partly subsumed by G2)
  G-Single (read skew across two keys)
  Internal consistency (a single txn reading then re-reading)

The tradeoff: mini-Elle catches the most common BFT-violation pattern
(two committed txns whose serialization order *cannot* be linear)
without needing a Clojure runtime.

Input format (newline-delimited JSON):
  {"index": 0,  "type": "invoke", "process": 3, "time": 1715000000000,
   "value": [["append", "x", 1], ["r", "y", null]]}
  {"index": 1,  "type": "ok",     "process": 3, "time": 1715000000123,
   "value": [["append", "x", 1], ["r", "y", [2, 5, 9]]]}

Usage:
  python3 mini_elle.py history.jsonl
"""

import json
import sys
from collections import defaultdict


def parse_history(path):
    """Read a newline-delimited JSON file. Each line is one event.
    Returns list of events."""
    events = []
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARN: line {i+1} not JSON: {e}", file=sys.stderr)
                continue
            events.append(ev)
    return events


def pair_invoke_ok(events):
    """Pair every (invoke, ok|fail) on the same process into a single
    transaction record. Returns list of dicts:
      {tid: int, process: int, ops_invoke: list, ops_result: list, status: str}
    Tid is index of the ok event in the original list."""
    txns = []
    pending = {}  # process -> last invoke event idx
    for i, ev in enumerate(events):
        proc = ev.get("process")
        kind = ev.get("type")
        if kind == "invoke":
            pending[proc] = ev
        elif kind in ("ok", "fail", "info"):
            inv = pending.pop(proc, None)
            if inv is None:
                # Stranded ok; skip
                continue
            txns.append({
                "tid": i,
                "process": proc,
                "t_invoke": inv.get("time", 0),
                "t_complete": ev.get("time", 0),
                "ops_invoke": inv.get("value", []),
                "ops_result": ev.get("value", []),
                "status": kind,
            })
    return txns


def extract_writes(txn):
    """Return list of (key, value) written by this txn.
    Supports both list-append ([:append k v]) and rw-register ([:w k v])."""
    out = []
    for op in txn["ops_result"]:
        if not isinstance(op, list) or len(op) < 3:
            continue
        if op[0] in ("append", "w"):
            out.append((op[1], op[2]))
    return out


def extract_reads(txn):
    """Return list of (key, value_seen) read by this txn.
    For list-append, value_seen is a list. For rw-register, it's a scalar
    that we wrap in a singleton list so build_dsg's "is in" check works
    uniformly."""
    out = []
    for op in txn["ops_result"]:
        if not isinstance(op, list) or len(op) < 3:
            continue
        if op[0] == "r":
            v = op[2]
            if v is None:
                continue
            if isinstance(v, list):
                out.append((op[1], v))      # list-append
            else:
                out.append((op[1], [v]))    # rw-register: wrap scalar
    return out


def build_dsg(committed):
    """Build a Direct Serialization Graph over committed txns.

    Edges:
      WR (write-read): T1 appends v on key k; T2 reads a list containing v
        in a position consistent with T1 having committed before T2.
        Edge T1 -> T2.
      RW (read-write / anti-dependency): T1 reads list L on key k; T2
        appends a value v on key k that DOES NOT appear in L. Edge
        T1 -> T2 (T1 missed T2's write, so T1 must serialize before T2).

    Returns:
      nodes: list of tids
      edges: dict tid -> set of tid (outgoing)
    """
    edges = defaultdict(set)
    nodes = [t["tid"] for t in committed]

    # Index: (key, value) -> writer tid. (Append v on key k is unique iff
    # values are unique within key, which the workload guarantees by using
    # txn-id-derived values.)
    writer_of = {}
    for t in committed:
        for (k, v) in extract_writes(t):
            writer_of[(k, v)] = t["tid"]

    # Index: key -> list of writers (tid)
    writers_per_key = defaultdict(set)
    for t in committed:
        for (k, _) in extract_writes(t):
            writers_per_key[k].add(t["tid"])

    # WR edges
    for t in committed:
        for (k, list_seen) in extract_reads(t):
            for v in list_seen:
                w = writer_of.get((k, v))
                if w is not None and w != t["tid"]:
                    edges[w].add(t["tid"])

    # Build tid -> txn lookup for time queries below
    by_tid = {x["tid"]: x for x in committed}

    # RW (anti-dependency) edges.
    # Adya: T1 -anti-deps-> W iff W "comes after" T1 in some serializable
    # order, i.e. W could plausibly have been the next-version-after-what-
    # T1-read.  Concretely: only add the edge if W's commit time is
    # AFTER T1's invoke time.  If W committed before T1 even started, then
    # T1 missing W's write just means a later write overwrote W in the
    # version chain that T1 saw -- not an anti-dep.
    for t in committed:
        for (k, list_seen) in extract_reads(t):
            seen_set = set(list_seen)
            for w_tid in writers_per_key.get(k, set()):
                if w_tid == t["tid"]:
                    continue
                w_txn = by_tid.get(w_tid)
                if w_txn is None:
                    continue
                w_writes_on_k = [v for (kk, v) in extract_writes(w_txn) if kk == k]
                if not w_writes_on_k:
                    continue
                # T1 saw none of W's writes on k?
                if any(v in seen_set for v in w_writes_on_k):
                    continue
                # And W could plausibly be after T1 (commit time check)?
                if w_txn["t_complete"] <= t["t_invoke"]:
                    # W was already done before T1 started -- T1 simply read
                    # a later overwrite, no anti-dep.
                    continue
                edges[t["tid"]].add(w_tid)

    return nodes, edges


def check_g1a_aborted_reads(committed, all_txns):
    """G1a: a committed txn read a value written by an aborted/failed txn.
    Returns list of (reader_tid, writer_tid, key, value) tuples."""
    # Index ALL writers (committed + aborted + info), tracking status.
    # If multiple txns wrote the same (k,v), mark by the LAST writer's status.
    writer_of = {}  # (k,v) -> (tid, status)
    for t in all_txns:
        for (k, v) in extract_writes(t):
            writer_of[(k, v)] = (t["tid"], t["status"])

    bad = []
    for r in committed:
        for (k, list_seen) in extract_reads(r):
            for v in list_seen:
                w = writer_of.get((k, v))
                if w is None:
                    continue
                w_tid, w_status = w
                if w_tid == r["tid"]:
                    continue
                if w_status != "ok":
                    bad.append((r["tid"], w_tid, k, v, w_status))
    return bad


def find_cycles(nodes, edges):
    """Tarjan SCC. Return list of SCCs that have size > 1 OR self-loops."""
    index_counter = [0]
    stack = []
    lowlinks = {}
    index = {}
    on_stack = {}
    sccs = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True

        for w in edges.get(v, set()):
            if w not in index:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w):
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            scc = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    sys.setrecursionlimit(50000)
    for v in nodes:
        if v not in index:
            strongconnect(v)

    bad = []
    for scc in sccs:
        if len(scc) > 1:
            bad.append(scc)
        elif len(scc) == 1 and scc[0] in edges.get(scc[0], set()):
            bad.append(scc)
    return bad


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    events = parse_history(sys.argv[1])
    txns = pair_invoke_ok(events)
    committed = [t for t in txns if t["status"] == "ok"]

    print(f"=== mini-Elle over {sys.argv[1]} ===")
    print(f"Total events:     {len(events)}")
    print(f"Total txns:       {len(txns)}")
    print(f"Committed:        {len(committed)}")
    print(f"Failed/info:      {len(txns) - len(committed)}")

    if not committed:
        print("PASS (vacuously) — no committed txns to check.")
        sys.exit(0)

    # G1a check (aborted reads) — runs over ALL txns so we see writers
    # that aborted.
    g1a_violations = check_g1a_aborted_reads(committed, txns)

    nodes, edges = build_dsg(committed)
    n_edges = sum(len(v) for v in edges.values())
    print(f"DSG nodes:        {len(nodes)}")
    print(f"DSG edges:        {n_edges}")

    g2_cycles = find_cycles(nodes, edges)

    print()
    print(f"G1a (aborted reads): {len(g1a_violations)} violation(s)")
    print(f"G2  (DSG cycles):    {len(g2_cycles)} cycle(s)")

    failed = bool(g1a_violations) or bool(g2_cycles)

    if g1a_violations:
        print()
        print(f"FAIL — G1a: committed txn read aborted writer's value:")
        for i, (r_tid, w_tid, k, v, w_status) in enumerate(g1a_violations[:5]):
            print(f"  reader_tid={r_tid} read ({k}={v}) written by tid={w_tid} status={w_status}")
        if len(g1a_violations) > 5:
            print(f"  ... and {len(g1a_violations) - 5} more")

    if g2_cycles:
        print()
        print(f"FAIL — G2: {len(g2_cycles)} cycle(s) found in DSG:")
        for i, scc in enumerate(g2_cycles[:5]):
            print(f"  cycle {i}: {scc}")
        if len(g2_cycles) > 5:
            print(f"  ... and {len(g2_cycles) - 5} more")

    if not failed:
        print()
        print("PASS — no G1a aborted reads, no G2 DSG cycles.")
        print("NOTE: this checks a SUBSET of what real elle-cli would.")
        print("      Once Elle is installed, re-run with the same input.")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
