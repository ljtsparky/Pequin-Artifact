# Project Timeline & Forward Plan

> CS 598 FTS — Removing the Sister-Replica Assumption from Pesto
> Last updated: 2026-05-06

This doc tracks **what we've done** (each step + where its output lives) and
**what's left** (each pending experiment + rough how-to).

---

# Part A — What We've Done

## Phase 0 — Codebase familiarization & local single-node tests

| Step | Output |
|------|--------|
| Read Pesto SOSP'25 paper, especially §B.10 | `/home/student/CS598FTS/pesto_sosp25.pdf` |
| Read Basil SOSP'21 (Pesto's parent) | `/home/student/CS598FTS/basil_sosp21.pdf` |
| Pequin / Pesto codebase walkthrough | `docs/pequin_codebase_overview.md` |
| Local single-node smoke tests (Pesto compiles & runs) | `docs/single_node_tests.md` |
| Existing artifact (vendor source) | `Pequin-Artifact/` |

**Key takeaways**: identified sister-replica assumption as the structural
restriction (configuration.cc:212 panics on heterogeneous shard sizes;
common.cc:2225 IsReplicaInGroup uses host-based matching).

---

## Phase 1 — Code implementation (heterogeneous-membership extension)

Branch: `cross-shard-membership` on `https://github.com/ljtsparky/Pequin-Artifact.git`
HEAD at experiment time: `17bb4c05`. Total: 24 files / ~1 213 lines /
4 commits.

### Files touched

| File | Change | Purpose |
|------|--------|---------|
| `src/lib/configuration.{h,cc}` | per-shard `n`/`f` parser, `group_f` directive | heterogeneous config support |
| `src/store/pequinstore/common.{h,cc}` | per-group `QuorumSize(config, group)` overloads, `IsReplicaInGroupHet` | per-shard quorum computation |
| `src/store/pequinstore/membership.{h,cc}` (NEW) | `MembershipManager` class | shard membership cert generation/verification |
| `src/store/pequinstore/pequin-proto.proto` | `ShardMembershipCert`, `SnapshotCert`, `ReplicaKeyInfo`, `SnapshotVote` | new wire messages |
| `src/store/pequinstore/server.{h,cc}` | `VerifyForeignSSCert`, `GenerateSnapshotVote` (defined, not yet wired) | server-side cert handlers |
| `src/store/pequinstore/tests/membership_test.cc` (NEW) | unit tests | cert generation + verification |
| `src/store/benchmark/async/benchmark.cc` | `--elle_history_path` flag (Phase 4) | Elle history capture |
| `src/store/benchmark/async/rw-sql/rw-sql_transaction.{h,cc}` | per-txn JSON history logger (Phase 4) | Elle history capture |

### Status at end of Phase 1

| Capability | State |
|-----------|------:|
| Per-shard `n`/`f` parsing | ✅ working |
| Per-shard quorum sizing on the protocol hot path | ✅ working |
| Membership cert generation at server startup | ✅ working |
| Membership cert verification (unit tests) | ✅ working |
| Snapshot cert generation/verification on cross-shard hot path | 🟡 code exists, not wired into `querysync-server.cc` |

---

## Phase 2 — 18-node CloudLab deployment

Cluster: CloudLab Utah, 18 × `amd` nodes.

### Files

| File | Purpose |
|------|---------|
| `setup_18_nodes.sh` | one-shot: SSH plumbing via geni-get, Ed25519 key sync, binary verification |
| `lab_ssh.txt` | 18 hostnames (12 servers × 2 shards + 6 clients) |
| `run_byzantine_experiment.sh` | orchestrator for honest + byzantine runs (env-var driven) |
| `run_heterogeneous_experiment.sh` | orchestrator for n=6 + n=11 heterogeneous run |
| `scripts/redeploy_18_nodes.sh` | parallel SSH `git pull` + `make` across all nodes |

### Setup output

| Artifact | Path |
|----------|------|
| Setup logs | `pesto-results/20260505T011554Z/` … `20260505T013538Z/` (early setup-only runs) |
| Per-experiment timestamped run dir | `pesto-results/<UTC-timestamp>/` (or `het-<UTC-timestamp>/` for Exp6) |
| Per-run artifacts inside each run dir | `AGGREGATE.md` + `configs/` + `logs/` + `run_params.txt` + `stats/` |

---

## Phase 3 — Experiments (5 successful + 2 broken/learned-from)

All experiments documented in `pesto-results/INDEX.md`. Each has its
own subdirectory containing:
- `configs/shard.config` — what was deployed
- `logs/server-*.log`, `logs/client-*.log` — raw stderr per node
- `stats/client-*.json` — Pesto's per-client stats output
- `run_params.txt` — env vars used to launch
- `AGGREGATE.md` — human-written summary with throughput, commit %, observations

### 3.1 — Run 8 (first byzantine run)

| Field | Value |
|------|------|
| Path | `pesto-results/20260505T015522Z/` |
| What | First end-to-end byzantine run (omission mode) |
| Config | `BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=1 BYZ_REPLICA_MODE=inconsistency` |
| Result | 32.7 tx/s, 70.6 % commit, 982 commits |
| Significance | Proved byz injection works end-to-end |

### 3.2 — Exp1 (honest baseline)

| Field | Value |
|------|------|
| Path | `pesto-results/20260505T025855Z/` |
| What | No faults anywhere — reference point for everything else |
| Config | `BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0` |
| Result | 33.9 tx/s, 68.9 % commit, 1 018 commits, 100 % fast-path |

### 3.3 — Exp2 (byzantine via crash)

| Field | Value |
|------|------|
| Path | `pesto-results/20260505T030152Z/` |
| What | Byz replica using full process crash (not silent omission) |
| Config | `BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=1 BYZ_REPLICA_MODE=failure` |
| Result | 32.8 tx/s, 71.5 % commit |
| Significance | Confirms protocol treats "didn't reply" and "isn't there" the same |

### 3.4 — Exp3 + Exp3b (cross-shard probes)

| Field | Value |
|------|------|
| Paths | `pesto-results/20260505T030630Z/` (NUM_TABLES=2) and `…T031149Z/` (NUM_TABLES=4) |
| What | Tried to drive cross-shard txns by varying table count |
| Result | **0 cross-shard txns out of 6 412 commits** across all 5 runs |
| Root cause analysis | `pesto-results/CROSS_SHARD_FINDING.md` |
| Why | `RWSQLPartitioner::operator()` partitions by `EncodeTable(table_name) % nshards`. Each table → one shard. Each rw-sql txn touches one table → never spans shards. |
| Implication | SS-CERT verifier code is correct in isolation but never invoked at runtime |

### 3.5 — Exp6 (heterogeneous)

| Field | Value |
|------|------|
| Path | `pesto-results/het-20260505T031658Z/` |
| What | Shard 0 (n=6, f=1) + Shard 1 (n=11, f=2), 1 client, all honest |
| Result | 408 commits in 30s, 100 % commit, 100 % fast-path, no panics |
| Significance | Direct proof the per-shard quorum machinery negotiates 5-vote and 9-vote quorums correctly in the same run |
| Caveat | Byzantine injection was OFF in this run |

### 3.6 — Elle-instrumented runs

| Field | Honest | Byzantine |
|------|--------|-----------|
| Path | `pesto-results/20260505T104108Z/` | `pesto-results/20260505T104430Z/` |
| What | Same as Exp1 / Exp2 but with Elle history capture | |
| Commits | 1 736 | 1 702 |
| DSG edges | 16 | 21 |
| mini-Elle G2 verdict | **PASS** | **PASS** |
| Elle JSON output | `elle/client-*.jsonl` inside each run dir | |

### 3.7 — Failed runs (kept for the record)

| Path | Failure | Lesson |
|------|---------|--------|
| `pesto-results/20260505T024314Z/` | Port collision from zombie processes | Added pre-cleanup `killall -9 server benchmark` to orchestrator |
| `pesto-results/20260505T025255Z/` | Empty stats `{}` files | Pesto's `benchmark.cc` calls Cleanup twice on SIGTERM; fix = scp stats BEFORE killing benchmark |

---

## Phase 4 — Verification framework

Two layers, increasing rigor.

### Layer 1 — Protocol-invariant checker

| Item | Path |
|------|------|
| Tool | `scripts/dsg_check.py` (175 lines) |
| What it checks | `commits ≤ prepares`, `attempts ≥ commits + aborts`, `fast ≤ prepares`, cross-shard count |
| Input | per-client stats JSON files inside any `pesto-results/<run>/stats/` |
| Verdict on all 5 successful runs | PASS — 0 violations across 5 829 attempted txns |
| Limitation | counter relationships only; cannot see actual data values |

### Layer 2 — Data-layer cycle checker (Elle-style)

| Item | Path |
|------|------|
| Tool | `scripts/mini_elle.py` (286 lines) |
| Wrapper | `scripts/elle_check.sh` |
| Synthetic test | `scripts/test_mini_elle.sh` |
| What it checks | G2 anti-dependency cycles in DSG (Adya semantics) |
| Algorithm | builds DSG with WR + RW edges; Tarjan SCC; reports any SCC > 1 node |
| Time-order filter | anti-dep T1→W only added if `w.t_complete > t.t_invoke` (avoids phantom cycles) |
| Input | per-client `.jsonl` files in `pesto-results/<run>/elle/` (emitted by patched rw-sql benchmark) |
| Output format compatibility | JSONL identical to `ligurio/elle-cli` — swap-in is one hour |
| Verdict | Honest 1 736 commits → PASS; Byzantine 1 702 commits → PASS |
| Documentation | `pesto-results/ELLE_RESULTS.md`, `docs/elle_integration_log.md` |

### Pesto-side patch for Layer 2

| File | Change |
|------|--------|
| `Pequin-Artifact/src/store/benchmark/async/benchmark.cc` | added `DEFINE_string(elle_history_path, "", "...")` |
| `Pequin-Artifact/src/store/benchmark/async/rw-sql/rw-sql_transaction.{h,cc}` | per-txn `elle_ops_` buffer; `EllInit/EllNowNs/EllEmit`; `:invoke`/`:ok`/`:fail` JSON events; unique value scheme `(client_id<<24)\|seq` to avoid value collisions |

---

## Phase 5 — Bugs caught & fixed along the way

| # | Symptom | Root cause | Fix |
|---|---------|------------|-----|
| 1 | sandbox blocked downloading real Elle (lein/jar) | code-from-external execution policy | wrote mini-Elle in pure Python |
| 2 | mini-Elle reported a 700+ node phantom cycle on honest baseline | `value++` collisions: 12.8 % of (key,value) write pairs had ≥2 writers under contention | commit `23806aff` — when `--elle_history_path` set, write `(client_id<<32)\|seq` |
| 3 | every txn aborts silently → empty Elle history | `client_id<<32` overflowed Pesto's auto-generated `INT32` value column | commit `17bb4c05` — pack as `(client_id<<24)\|seq`, keep high bit 0 |
| 4 | mini-Elle reported a 3-node phantom cycle on byz run | missing time filter on anti-dep edges | `scripts/mini_elle.py` — only add T1→W if `w.t_complete > t.t_invoke` |

| Operational bugs (not Pesto-side) |
|-----------------------------------|
| double-Cleanup in `benchmark.cc` writes empty stats — fix: scp stats before SIGTERM |
| zombie processes hold port 7000 across reruns — fix: pre-cleanup `killall -9` at orchestrator start |

---

## Phase 6 — Documentation

| File | Purpose |
|------|---------|
| `docs/pequin_codebase_overview.md` | tour of Pesto/Pequin source tree |
| `docs/single_node_tests.md` | early local sanity testing |
| `docs/multinode_experiment_log.md` | 18-node deployment journal |
| `docs/byz_injection_and_test_validity.md` | what `--pequin_simulate_*` flags do |
| `docs/testing_survey.md` | survey of BFT testing tools (Twins, ByzzFuzz, Jepsen, Elle, …) |
| `docs/elle_integration_log.md` | step-by-step Elle integration journal |
| `docs/evaluation_and_correctness.md` | broad evaluation discussion |
| `docs/presentation.md` | 10-min final talk script |
| `pesto-results/INDEX.md` | one-line summary of every run |
| `pesto-results/CROSS_SHARD_FINDING.md` | analysis of "0 cross-shard txns" |
| `pesto-results/ELLE_RESULTS.md` | Layer 2 verdict + bug timeline |
| `ppt_figures/` | 14 PNG figures for the talk |

---

# Part B — What We're Going to Do Next

Sorted in priority order. Estimates assume one engineer working full-time
and the existing 18-node cluster.

## Next-1 — Port a TPC-C-style workload (the most important gap)

### Why
Our cross-shard SS-CERT verifier code (`Server::VerifyForeignSSCert`,
`Server::GenerateSnapshotVote`) compiled and unit-tests pass, but
`pesto-results/CROSS_SHARD_FINDING.md` shows **0 cross-shard txns
in 6 412 commits**. The verifier is dead code at runtime. We need a
workload that naturally produces transactions touching ≥ 2 shards.
TPC-C's NewOrder transaction includes ~10 % "remote warehouse" line
items by spec — exactly that.

### How
1. Use the existing `WarehouseSQLPartitioner` (already in the codebase)
   instead of `RWSQLPartitioner`.
2. Implement the 5 TPC-C transaction types in
   `src/store/benchmark/async/sql/tpcc/`:
   - NewOrder (45 %), Payment (43 %), Delivery (4 %), OrderStatus (4 %),
     StockLevel (4 %).
   - Pesto's TPC-C harness exists in part — fill in the missing txn classes.
3. Add an initial-data-load step to the orchestrator: N warehouses ×
   10 districts × 3 000 customers, ~100 000 items.
4. Re-run on the 18-node cluster with `BENCH=tpcc`, multiple warehouses
   spread across shards.
5. Re-run `dsg_check.py` and `mini_elle.py` to confirm the cross-shard
   verifier path is exercised (`txn_groups[2]+ > 0`).

### Estimated effort
1 week (most time on data loading + fairness rules).

### Acceptance criterion
`dsg_check.py` reports a non-zero cross-shard count, and at least one
`Server::VerifyForeignSSCert` call site fires (add a counter and check
in `pesto-results/<run>/logs/server-*.log`).

---

## Next-2 — Combine heterogeneous + byzantine in one run

### Why
Exp6 ran heterogeneous (n=6 + n=11) with byzantine OFF; Exp1/Exp2 ran
byzantine with homogeneous n=6. We never combined them, so we have no
data on whether the per-shard quorum machinery degrades correctly when
shard 1 (n=11, f=2) has 2 byzantine replicas.

### How
1. Edit `run_heterogeneous_experiment.sh` to accept the same byz env
   vars as `run_byzantine_experiment.sh` (`BYZ_PER_SHARD`,
   `BYZ_REPLICA_MODE`, `BYZ_CLIENT_COUNT`).
2. Run with `BYZ_PER_SHARD=1` (1 byz per shard — that's f=1 for shard 0,
   f/2 for shard 1) and separately with `BYZ_PER_SHARD=2` (saturates
   shard 0 at f, shard 1 at f).
3. Confirm: shard 1 still commits with 9-vote quorum, shard 0 still
   commits with 5-vote quorum.

### Estimated effort
Half a day (mostly waiting for runs).

### Acceptance criterion
Throughput within ~5 % of the all-honest heterogeneous run.

---

## Next-3 — Twins-style lying-client test

### Why
Our current "byzantine client" model is just process crash mid-txn.
Real BFT safety bugs come from clients that *equivocate* — e.g., send
different read sets to different shards in a cross-shard transaction.
The Twins paper (OPODIS'21) injects this kind of fault by running two
client processes with the same identity that diverge in behavior.

### How
1. Add a `--pequin_twin_of=<id>` client flag: when set, the client
   pretends to be `<id>` (uses its key + client_id) but sends a
   modified read/write set on every Nth transaction.
2. Detection happens at the data layer: if the modified set commits,
   `mini_elle.py` should find a cycle.
3. If `mini_elle.py` does NOT find the cycle, that's a real safety bug
   in Pesto and we file it upstream.

### Estimated effort
1 week (~150 lines of C++ for the twin client + new mini-Elle test
case).

### Acceptance criterion
A documented run where the twin client's modified set is rejected by
the protocol AND a separate run where (deliberately) bypassing some
check produces a `mini_elle.py` cycle, proving the verifier catches
real anomalies.

---

## Next-4 — Real Elle CLI integration

### Why
Our `mini_elle.py` only checks G2 anti-dep cycles. Real Elle also checks
G0 (dirty write), G1a/G1b (aborted/intermediate read), G1c (cyclic
information flow), G-Single (read skew). Our JSON history is already
format-compatible (`pesto-results/ELLE_RESULTS.md` confirms this).

### How
1. Get explicit permission to install `ligurio/elle-cli`'s pre-built jar
   (sandbox blocked auto-download; needs interactive sudo).
2. Verify Java 8+ already present on the dev box (yes, 11.0.30).
3. Run:
   ```bash
   java -jar elle-cli.jar --model rw-register pesto-results/<run>/elle/merged.jsonl
   ```
4. Compare verdict against `mini_elle.py` — they should agree on G2;
   real Elle may surface additional anomalies our subset missed.

### Estimated effort
1 hour assuming permission granted.

---

## Next-5 — Wire the snapshot-cert verifier into `querysync-server.cc`

### Why
Static analysis (`pesto-results/CROSS_SHARD_FINDING.md`) shows
`Server::VerifyForeignSSCert` and `Server::GenerateSnapshotVote` are
defined but have **0 hot-path call sites** in `querysync-client.cc`
or `querysync-server.cc`. Once Next-1 (TPC-C) generates real cross-shard
txns, the verifier needs to actually fire on the receive side.

### How
1. In `querysync-server.cc`, when receiving a `SyncClientProposal`
   with a `foreign_ss_cert` field set, call `VerifyForeignSSCert()`
   before processing.
2. In `querysync-client.cc`, when constructing a cross-shard query
   request, attach the local shard's `SnapshotCert` (collect 2f+1
   replica votes via `GenerateSnapshotVote`).
3. Add a counter in `server.cc` for `ss_cert_verifications_done_` and
   surface it in stats so we can confirm it ticks during runs.

### Estimated effort
Half a day.

### Acceptance criterion
`ss_cert_verifications_done_ > 0` in TPC-C run logs.

---

## Next-6 — Live membership reconfiguration (research-level)

### Why
Static membership cert is a snapshot in time. A real deployment needs
to add/remove replicas while online (e.g., `group_f` bumps from 1 → 2
when an organization joins). This is an open research problem in BFT
and is **out of scope** for the course project — listed for completeness.

### Likely shape
- Start a 2-phase membership change: propose new cert with version+1,
  collect 2f+1 votes from old membership, atomically swap.
- Need to handle in-flight txns at the boundary (drain or replay).
- Equivocation between old and new memberships is the hard part.

---

# Quick reference — how to reproduce any past run

```bash
# 1. fresh CloudLab profile setup
bash setup_18_nodes.sh

# 2. honest baseline (Exp1)
BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0 bash run_byzantine_experiment.sh

# 3. byzantine via omission (Run 8)
BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=1 BYZ_REPLICA_MODE=inconsistency \
  bash run_byzantine_experiment.sh

# 4. byzantine via crash (Exp2)
BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=1 BYZ_REPLICA_MODE=failure \
  bash run_byzantine_experiment.sh

# 5. cross-shard probe (Exp3 / Exp3b)
NUM_TABLES=2 bash run_byzantine_experiment.sh
NUM_TABLES=4 bash run_byzantine_experiment.sh

# 6. heterogeneous (Exp6)
bash run_heterogeneous_experiment.sh

# 7. Elle-instrumented runs (need 17bb4c05+ deployed first)
BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0 bash run_byzantine_experiment.sh
LATEST=$(ls -td pesto-results/2026* | head -1)
bash scripts/elle_check.sh $LATEST   # expect: PASS — no cycles

# 8. protocol-invariant check on any run
python3 scripts/dsg_check.py pesto-results/<timestamp>
```

When code changes on the local repo, push the branch and:

```bash
bash scripts/redeploy_18_nodes.sh   # parallel git pull + make on all 18 nodes
```
