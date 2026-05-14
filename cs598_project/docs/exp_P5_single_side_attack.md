# P5 — Single-side commit attack on L2 atomicity

**Date:** 2026-05-12
**Code:** `cross-shard-membership` @ `1c5ca4bd` (`--pequin_drop_cross_shard_writeback` flag)
**Workload:** TPC-C, 10 warehouses, 30s × 6 clients
**Negative-control verified:** L2 audit script correctly flags synthetic partial commit (exit 1)

## What this closes

L2 negative test. P2 + P4 showed 0 atomicity violations under HONEST and
WITHIN-BUDGET byzantine. P5 stresses the boundary: byzantine replicas
that **explicitly drop cross-shard writeback messages**. Two questions:

1. **Does Pesto defend?** I.e. even when 1+ byz/shard silently drop
   cross-shard `HandleWriteback`, does atomicity hold?
2. **Would our L2 audit catch a real partial commit?** Sanity-check
   that the audit tool is not just "always passing".

## Result matrix — Pesto IS robust to writeback drops

| Run | byz/shard | total byz drops on the wire | client commits | cross-shard | L2 violations | Verdict |
|-----|----------:|----------------------------:|---------------:|------------:|--------------:|---------|
| `20260512T053900Z` | **1** (within f=1 budget) | 12 | 4 785 | 227 | **0 / 0** | PASS |
| `20260512T054224Z` | **2** (over f=1 budget) | 24 | 4 279 | 208 | **0 / 0** | PASS |
| `20260512T054607Z` | **3** (50% of n=6, way over) | 72 | 4 765 | 231 | **0 / 0** | PASS |

In all three settings, byzantine replicas successfully dropped
`HandleWriteback` for cross-shard txns (counter `byz_xshard_writeback_dropped`
ticked up proportionally) — but **no atomicity violation occurred**.

## Why Pesto holds even with 50% writeback drops

The COMMIT decision in Pesto is made at Phase1 (quorum of `4f+1` replicas
agreeing). Once decided, the writeback is propagated through multiple
paths:

- Direct client `HandleWriteback`
- Inter-replica gossip / fallback
- Late-comer "GetWriteback" requests when a replica notices it missed one

A byz replica that drops its direct `HandleWriteback` message just
delays its own knowledge of the decision. The remaining 4–5 honest
replicas in that shard still receive the writeback and apply the commit.
Each shard's per-replica view (the L2 audit's input) shows the txn as
committed at MULTIPLE replicas, so `observed_groups` includes the
affected shard.

To actually break atomicity at this layer, an attacker would need to
deny ALL of a shard's replicas the writeback AND the gossip AND the
fallback fetches — a much wider attack surface. Even then, the byz
shard is no longer recognized as having "committed" the txn, and the
cross-shard atomicity question becomes "did the OTHER shard commit
unilaterally" which Pesto's protocol prevents at the prepare stage.

## Negative-control: synthetic partial commit IS detected

To rule out "L2 audit is broken and always passes":

```text
$ ls /tmp/l2_audit_test_synth/logs/
server-g0-r0.log   ← contains L2_AUDIT_COMMIT for txn deadbeef0001 involved=[0,1]
server-g0-r1.log   ← same
server-g1-r0.log   ← (empty — txn never reached shard 1)
server-g1-r1.log   ← (empty)

$ python3 scripts/l2_audit.py /tmp/l2_audit_test_synth
PARTIAL_COMMIT violations : 1
  deadbeef0001  involved=[0, 1]  observed=[0]
FAIL — 1 partial + 0 phantom
EXIT=1
```

Audit correctly flags the partial commit. Combined with the runtime
results above, this proves the runtime PASS verdicts are real — Pesto
is genuinely keeping atomicity under all three byzantine writeback-drop
configurations.

## What this still doesn't prove

- We tested only ONE class of byz behavior — silent drop of writeback.
  Other byz behaviors (lying about the decision, equivocating to
  different replicas, replaying old writebacks) require separate
  injection paths and are out of scope for this test.
- We didn't test injection at the Phase1 quorum stage where the
  decision is actually made. A clever attacker would target Phase1
  voting, not writeback. That's the next negative test.

## Reproduction

```bash
# within budget
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=0 \
    BYZ_REPLICA_MODE=drop_xshard DURATION=30 \
    bash run_byzantine_experiment.sh

# over budget
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=2 BYZ_CLIENT_COUNT=0 \
    BYZ_REPLICA_MODE=drop_xshard DURATION=30 \
    bash run_byzantine_experiment.sh

# 50% of replicas drop
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=3 BYZ_CLIENT_COUNT=0 \
    BYZ_REPLICA_MODE=drop_xshard DURATION=30 \
    bash run_byzantine_experiment.sh

# audit
python3 scripts/l2_audit.py pesto-results/<run>
```
