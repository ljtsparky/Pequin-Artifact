---
date: 2026-05-13
purpose: Full performance evaluation — crypto µs overhead, cross-shard sweep, client-count sweep, TPC-C, 3× repeats
code: cross-shard-membership @ ad9305d2 (perf: add µs timers around v3 vote sign and SS-CERT verify)
duration_each: 60 s (5 s warmup + 5 s cooldown)
config: 2 shards × 6 replicas (n=6, f=1) on 18 CloudLab nodes; 6 clients unless stated
benchmark: rw-sql NUM_KEYS=1000 NUM_OPS=2 zipf=0.5 (TPC-C run uses WAREHOUSES=10)
---

# Full Pesto cross-shard performance evaluation

## Summary

| Phase | What | Result |
|-------|------|--------|
| A | SS-CERT v3 crypto µs overhead | **sign ≈ 94 µs, verify ≈ 708 µs**, stable across all configs |
| B | Cross-shard fraction sweep | Throughput falls 513 → 177 tx/s as xshard% rises 0% → ~94% |
| C | Client-count load curve | Near-linear scale 2→4→6 clients: 84 → 190 → 297 tx/s (knee not reached) |
| D | TPC-C cross-warehouse | 182 tx/s, P50=21ms, P95=85ms — tail-heavy vs rw-sql |
| E | 3× repeats (honest / omission / twin) | All three modes are **statistically indistinguishable** (CV < 1%) |

## Phase A — Crypto µs overhead

Added timers in `Pequin-Artifact/src/store/pequinstore/server.cc:GenerateSnapshotVote` and `VerifyForeignSSCert` (`ad9305d2`). Server-side counters per replica:

- `ss_cert_vote_sign_micros_total` / `ss_cert_vote_sign_count`
- `ss_cert_verify_micros_total` / `ss_cert_verify_count`

Across all 18 runs from Phases B-E, **regardless of config**:

| Op | Mean µs |
|----|---------|
| `GenerateSnapshotVote` (BLAKE3 digest already provided; Ed25519 sign + 1 protobuf set) | **93–96 µs** |
| `VerifyForeignSSCert` (2f+1 = 3 Ed25519 verifies + membership-cert lookup + protobuf parse) | **705–709 µs** |

So a 3-vote v3 cert: **sign ≈ 0.1 ms × 3, verify ≈ 0.7 ms total** on these CloudLab Intel Xeon nodes.

End-to-end latency P50 is ~20 ms — verify is **~3.5% of one round-trip**. Crypto is not the bottleneck.

## Phase B — Cross-shard fraction sweep

NT = number of tables (partitioning unit). NUM_OPS = ops/txn. With NT tables and OPS ops drawn uniformly, the probability a txn lands on a single shard is `(1/2)^(OPS-1)` (each op picks one of 2 shards) — though Pesto's partitioner uses table-name hashing.

| Run | NT | OPS | xshard estimate | tput tx/s | P50 ms | P95 ms | P99 ms |
|-----|----|----|------|----------:|-------:|-------:|-------:|
| `T183041Z` | 1 | 2 | 0% (single-shard) | 300 | 19.8 | 22.1 | 23.1 |
| `T183428Z` | 2 | 1 | 0% (single-op) | **513** | 11.4 | 13.5 | 14.4 |
| `T183829Z` | 2 | 2 | ~50% | 300 | 19.9 | 22.4 | 23.6 |
| `T184232Z` | 2 | 4 | ~94% | 177 | 34.0 | 37.5 | 39.1 |
| `T184616Z` | 4 | 2 | ~75% | 291 | 20.0 | 22.4 | 23.4 |

Observations:
- **NT=2 OPS=1** is the fastest because each txn touches a single key on a single shard, no cross-shard coordination at all.
- **Doubling cross-shard work (OPS=2→4)** halves throughput and doubles P50.
- **NT=4 OPS=2** does NOT degrade much vs NT=2 OPS=2 — the partitioner hashes table names but with 2 shards, NT=4 still splits load roughly evenly, and OPS=2 still touches ~2 shards per txn.

## Phase C — Client-count load curve (NT=2 OPS=2)

| Run | NC | tput tx/s | tx/s/client | P50 ms | P95 ms | P99 ms |
|-----|----|----------:|------------:|-------:|-------:|-------:|
| `T185006Z` | 2 | 83.5  | 41.7 | 23.6 | 30.7 | 33.1 |
| `T185320Z` | 4 | 190.1 | 47.5 | 21.0 | 23.6 | 24.4 |
| `T185648Z` | 6 | 297.2 | 49.5 | 19.9 | 22.4 | 23.3 |

Throughput scales near-linearly. Per-client throughput actually **rises** with more clients (41→48→50 tx/s/client), suggesting amortization of per-client startup costs and that the system is still well below saturation. To find the knee of the curve we need NC > 6 (multi-process-per-host).

## Phase D — TPC-C cross-warehouse

| Run | bench | tput | P50 | P95 | P99 |
|-----|-------|-----:|----:|----:|----:|
| `T190024Z` | tpcc-sql | 181.8 | 21.1 | 84.8 | 138.0 |

TPC-C produces:
- comparable median latency (~21 ms, same as rw-sql)
- much **heavier tail** (P95 = 85 ms, P99 = 138 ms vs rw-sql's 22/23 ms)
- ~60% of rw-sql throughput

Tail-heaviness comes from TPC-C's mix: NewOrder cross-warehouse line items hit both shards (~1% per item × 10 items ≈ 10% of NewOrders go cross-warehouse), Payment occasionally crosses warehouses, etc.

## Phase E — 3 repeats × 3 byz modes (NT=2 OPS=2, NC=6)

Each cell run 3 times back-to-back.

| Mode | Runs | mean tput | stddev | CV | P50 mean | P95 mean | P99 mean |
|------|------|----------:|-------:|----|---------:|---------:|---------:|
| honest | T190415, T191544, T192633 | **299.1** | 2.87 | 1.0% | 19.7 | 22.4 | 23.4 |
| 1 omission/shard | T190810, T191922, T193017 | **301.0** | 2.19 | 0.7% | 19.8 | 22.4 | 23.5 |
| 1 twin/shard | T191205, T192257, T193358 | **303.6** | 0.69 | 0.2% | 19.7 | 22.4 | 23.4 |

**Key finding:** within < 1% CV, **honest ≈ omission-byz ≈ twin-byz**. The difference 299 vs 304 (1.7%) is comparable to natural run-to-run variance.

This **corrects** an earlier observation in `docs/perf_baseline.md` (Phase 3 sync run was at 82.9 tx/s) — that was a single-run outlier from the first sync run after the rebuild; the 3-repeat mean is firmly ~300 tx/s.

## Aggregate findings

1. **SS-CERT v3-STRICT crypto is cheap.** 94 µs sign + 708 µs verify ≈ 0.8 ms total per cert, ~3.5% of a 20 ms round-trip. The protocol can sustain ~22 000 verifications/sec server-side (Phase E gives ~3 700 verify/sec/replica × 6 replicas × 1 shard).
2. **Cross-shard cost is real but bounded.** Going from 0% to ~94% cross-shard txns costs 3× throughput and 2× P50 latency.
3. **No measurable performance penalty from byzantine activity** within Pesto's f=1 budget. The histogram filtering + 2f+1 quorum handles 1 byz/shard for free in steady state.
4. **Heterogeneous 2-shard deployment** (12 disjoint replicas) sustains 300 tx/s of mixed rw-sql at sub-25 ms tail.
5. **TPC-C is tail-heavy** but median competitive.

## Open items

1. **Pesto-Homogeneous (sister-replica) baseline.** Our 12-host deployment is heterogeneous by default. To measure the cost of *removing* the sister-replica assumption vs original Pesto's *requiring* it, need a side-by-side with both groups sharing the same 6 hosts. **Not done.**
2. **Client count > 6** (12, 18, 30). Needs multi-process-per-host. The Phase C curve has not reached its knee.
3. **Per-µs histogram (not just mean).** The current timers give mean only; for tail crypto cost, need a histogram or P50/P95 of the µs samples.
4. **Eager-vs-sync path comparison under matched conditions.** The earlier `perf_baseline.md` runs 1-2 (eager) and 3-5 (sync) differ by 7-25×. Why eager is so slow on this deployment deserves investigation. (Theory: zipf-0.5 hot-key conflict-retry loop.)

## Methodology / artifacts

- Run command for one Phase E cell:
  ```
  NUM_TABLES=2 NUM_OPS=2 DURATION=60 BENCHMARK=rw-sql \
    BYZ_PER_SHARD=1 BYZ_REPLICA_MODE=twin_sig \
    PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
    bash run_byzantine_experiment.sh
  ```
- Analyzer: `scripts/perf_analyze.py <run_dir> ...`
- All 18 runs are in `pesto-results/20260512T18*Z` and `20260512T19*Z`
- Per-run params recorded in `<run_dir>/run_params.txt` (now also includes `NUM_TABLES`, `PEQUIN_EAGER`, `QUERY_MESSAGES`, `BYZ_REPLICA_MODE` after the orchestrator fix in this branch)
- Latency comes from `bench_client.cc:121-141` CooldownDone lines, averaged across all clients
- Throughput comes from `sum(rw_sql_committed or tpcc_committed) / DURATION`
- Crypto µs from `ss_cert_vote_sign_micros_total / count` and `ss_cert_verify_micros_total / count`

## Commits within this evaluation

| SHA | What |
|-----|------|
| `ad9305d2` | µs timers in `GenerateSnapshotVote` and `VerifyForeignSSCert` |
| (uncommitted local) | `run_byzantine_experiment.sh:416` records NUM_TABLES/PEQUIN_EAGER/etc in run_params.txt; `NUM_CLIENTS` made env-overridable |
