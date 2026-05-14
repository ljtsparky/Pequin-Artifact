# P4 — TPC-C cross-shard + Byzantine combined

**Date:** 2026-05-12
**Code:** `cross-shard-membership` @ `fe81f8aa` (with L2 audit)
**Workload:** TPC-C, 10 warehouses, `--partitioner=warehouse`, 30s × 6 clients
**Faults:** 1 byzantine replica per shard (saturates f=1 limit on n=6 shards)

## Three-row comparison

| Run | Mode | Commits | Cross-shard (client view) | L2 audit (server view) | Partial | Phantom | Throughput | Verdict |
|-----|------|--------:|--------------------------:|-----------------------:|--------:|--------:|-----------:|---------|
| `20260512T033704Z` | **honest baseline** | 4 691 | 238 | **227 OK** | 0 | 0 | ~156 tx/s | PASS |
| `20260512T034016Z` | byz omission, 1/shard | 4 515 | 212 | **213 OK** | 0 | 0 | ~150 tx/s | **PASS** |
| `20260512T034301Z` | byz crash, 1/shard | 4 666 | 225 | **224 OK** | 0 | 0 | ~155 tx/s | **PASS** |

## Headline

Cross-shard atomicity holds under both byzantine fault models at the
f=1 saturation point. Throughput drop is **<5%** in both cases. **0
partial commits, 0 phantom commits across 664 cross-shard transactions**
spread over 3 runs.

## What this proves

L1 (protocol invariants) + L2 (cross-shard atomicity) under fault. Every
real cross-shard txn that the system commits, both shards (= every
involved replica majority) actually committed.

## What this still doesn't prove

- L3 (Adya semantics) on cross-shard data — TPC-C still has no Elle hooks.
  See P1.
- Equivocation: byz replica that says different things to different other
  replicas. We tested omission (silent withhold) and crash (process dies),
  not the harder lying-replica fault.
- f+1 or worse — over-budget fault count. Pesto's claim is f tolerance;
  beyond that, safety/liveness can collapse legally.

## Note on `BYZ_PER_SHARD=1` semantics in this orchestrator

The server flag is `--pequin_simulate_inconsistency=true` (omission) or
`--pequin_simulate_replica_failure=true` (crash). Both target the LAST
`BYZ_PER_SHARD` replicas in each shard's index. So with shard 0 = r0..r5
on hp090..hp122, the byz one is r5 on hp122. Same for shard 1 r5 on
hp130. Total = 2 byz across 12 servers, 1 per shard's f budget.

## Reproduction

```bash
# honest baseline
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0 \
  DURATION=30 bash run_byzantine_experiment.sh

# byz omission (silent withhold)
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=0 \
  BYZ_REPLICA_MODE=inconsistency DURATION=30 \
  bash run_byzantine_experiment.sh

# byz crash (process dies)
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=0 \
  BYZ_REPLICA_MODE=failure DURATION=30 \
  bash run_byzantine_experiment.sh

# audit each
python3 scripts/l2_audit.py pesto-results/<run>
```
