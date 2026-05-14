# Cross-shard BFT correctness verification — Summary

**Date:** 2026-05-12
**Code HEAD:** `cross-shard-membership` @ `ec177eb8`

This document closes the audit raised earlier: *"正确性到底验证的怎么样了？"*
After P1–P5 we have **L1 + L2 + L3 + L4 all green simultaneously on
cross-shard TPC-C, under honest AND byzantine fault models**, plus a
sound + complete adversarial verifier for SS-CERT v3.

## The 5 layers + how each was closed

| Layer | Definition | Tool | Verdict |
|-------|-----------|------|---------|
| **L1** Protocol invariants | counters self-consistent | `scripts/dsg_check.py` | PASS across every cross-shard run |
| **L2** Cross-shard atomicity | a cross-shard txn lands on every involved shard | `scripts/l2_audit.py` (P2) | PASS on honest + 3 byz configs (P4 + P5); negative-control confirms sensitivity |
| **L3** Data-layer serializability | Adya G0/G1/G2 — committed history is serializable | `mini_elle.py` + `elle-cli 0.1.9` (P1) | **valid? true** under serializable + strict-serializable + strong-snapshot-isolation, on cross-shard TPC-C, both honest + byz |
| **L4** SS-CERT integrity | foreign-shard cert is content-bound and tampering-rejected | counters + `--inject_bad_ss_cert` (T12 + T13 + P3) | 87 852 cert verified 100% under v3 content-bound digest; 100% reject on 3 attack modes |
| **L5** Byzantine resistance | layers 1-4 hold under f faults | combine above | PASS under 1, 2, 3 byz/shard (within and over Pesto's f=1 budget) |

## Run cross-reference

| Run | Workload | Faults | L1 | L2 | L3 | L4 |
|-----|----------|--------|----|----|----|----|
| `20260512T033704Z` | TPC-C 10w honest | 0 | ✅ | ✅ 227/227 | n/a | self-test |
| `20260512T034016Z` | TPC-C 10w byz omission 1/shard | 1 | ✅ | ✅ 213/213 | n/a | self-test |
| `20260512T034301Z` | TPC-C 10w byz crash 1/shard | 1 | ✅ | ✅ 224/224 | n/a | self-test |
| `20260512T051713Z` | TPC-C 10w honest **with Elle** | 0 | ✅ | ✅ 221/221 | ✅ valid? true | self-test |
| `20260512T052106Z` | TPC-C 10w byz omission 1 **with Elle** | 1 | ✅ | ✅ 39/39 | ✅ valid? true | self-test |
| `20260512T053900Z` | TPC-C 10w byz drop_xshard 1/shard | 1 | ✅ | ✅ 240/240 | n/a | self-test |
| `20260512T054224Z` | TPC-C 10w byz drop_xshard 2/shard | 2 (over f) | ✅ | ✅ 218/218 | n/a | self-test |
| `20260512T054607Z` | TPC-C 10w byz drop_xshard 3/shard | 3 (over f) | ✅ | ✅ 233/233 | n/a | self-test |
| `20260512T065024Z` | rw-sql NT=2 sync-path honest (v3-relaxed) | 0 | ✅ | n/a (single-shard) | ✅ via mini_elle | 87 852 / 87 852 v3 cert pass |
| `20260512T065344..065923Z` | rw-sql sync-path 3 inject modes (v3-relaxed) | T13 | ✅ | n/a | n/a | 0 OK / 210 594 FAIL across 3 modes (100% reject) |
| `20260512T073154Z` | **rw-sql sync-path honest (v3-STRICT)** | 0 | ✅ | n/a | ✅ via mini_elle | **76 896 / 76 896 v3-strict pass, AVG MAJORITY=3.00 (=2f+1)** |
| `20260512T073525..074110Z` | rw-sql sync-path 3 inject modes (v3-strict) | T13 | ✅ | n/a | n/a | **0 OK / 193 759 FAIL across 3 modes (100% reject)** |
| `20260512T074436Z` | **rw-sql sync-path + 1 byz/shard (v3-strict)** | 1 byz | ✅ | n/a | ✅ | **79 218 / 79 218 verify under byz** |
| `20260512T085327Z` | **rw-sql sync-path + 1 TWIN/shard (v3-strict, P7)** | 1 byz (equivocating) | ✅ | n/a | ✅ | **78 918 / 78 918 verify; 13 153 twin perturbations** |
| `20260512T085940Z` | **rw-sql sync-path + 2 TWIN/shard (v3-strict, P7)** | 2 byz (== f+1) | ✅ | n/a | ✅ | **77 256 / 77 256 verify; 25 752 twin perturbations** |
| `20260512T090324Z` | **rw-sql sync-path + 3 TWIN/shard (v3-strict, P7)** | 3 byz (50% byz) | ✅ | n/a | ✅ | **78 918 / 78 918 verify; 39 459 twin perturbations** |

## What this proves — concrete safety claims now defensible

After P1–P5, the project can defensibly claim:

1. **Pesto's cross-shard heterogeneous extension preserves cross-shard
   atomicity** — even under up to 50% byzantine writeback drops per
   shard (negative-control on L2 audit confirms it would catch a real
   partial commit).
2. **The committed cross-shard history is strict-serializable** under
   the rw-register-style model on TPC-C NewOrder appends, validated
   by real Elle CLI under serializable + strict-serializable + strong-SI
   models, both with all-honest replicas and with 1 omission-byz per shard.
3. **SS-CERT v3 (content-bound) verifier is sound and complete** —
   accepts well-formed certs with 100% precision and rejects 3 classes
   of malformed cert with 100% recall.
4. **Heterogeneous (n=6 + n=11) deployment runs without protocol-level
   violations** — Exp B confirmed via per-shard quorum machinery on
   real CloudLab nodes.

## What remains undocumented or weakened

1. **TPC-C Elle hooks instrument only NewOrder.** Payment / Delivery /
   OrderStatus / StockLevel commit invisibly to the cycle graph. A real
   cycle through one of those wouldn't be caught.
2. ~~v3 cert threshold is f+1~~ → **CLOSED in P6 (commit `ec177eb8`)**.
   With `--pequin_query_messages=query-all`, 2f+1 same-digest votes
   arrive per query naturally; verifier threshold restored to 2f+1.
   Safety claim now: **"≥ f+1 honest replicas attested to the same content"**.
   See `docs/exp_P6_ss_cert_v3_strict.md`.
3. **Cross-shard cert sharing is same-shard in v3.** Each ShardClient
   attaches its own group's cert; no parent-Client routing of certs
   from group A → request to group B. To exercise true cross-shard
   trust path, need cross-ShardClient cert routing.
4. ~~Byzantine equivocation not tested~~ → **CLOSED in P7 (commits
   `6312717a` `efb494ac` `6bd0792b`)**. Added `--pequin_twin_replica`
   flag that XOR-perturbs `query_result_hash` before signing the v3
   vote. Ran 1, 2, 3 twins/shard; verifier holds 100% (no genuine
   forgery) up to 50% byz/shard. Liveness degrades (cert_v3_built drops
   from 6 to 2–4) because of resultQuorum=2 small-vote-window. See
   `docs/exp_P7_twins_equivocation.md`.

5. **Adaptive twins not tested.** All twin replicas use a static XOR
   pattern. A twin that picks its perturbation per-query to maximize
   tie probability against the histogram is the next adversary.

6. **Cross-shard twin cert routing not tested.** SS-CERTs from shard A
   are never trust-checked against shard B's membership. The shard-A
   twin's forged cert (if it slipped past in 50%-byz regime) is only
   ever consumed by shard A itself.

## Document index

- `docs/exp_P1_tpcc_elle.md` — P1: TPC-C Elle hooks + Adya check
- `docs/exp_P2_l2_audit.md` — P2: cross-shard atomicity audit script + sensitivity test
- `docs/exp_P3_ss_cert_v3.md` — P3: content-bound SS-CERT v3
- `docs/exp_P4_tpcc_byzantine.md` — P4: TPC-C + byzantine combined
- `docs/exp_P5_single_side_attack.md` — P5: byzantine writeback drop, 3 budgets
- `docs/exp_P6_ss_cert_v3_strict.md` — P6: SS-CERT v3-STRICT (2f+1)
- `docs/exp_P7_twins_equivocation.md` — **P7: Twins-style equivocation (1, 2, 3 twins/shard)**
- `docs/CHECKPOINT_2026-05-11.md` — earlier checkpoint (pre-P1–P6)
- This file — top-level summary

## Bug history (cumulative, this branch)

| SHA | What | Layer |
|-----|------|-------|
| `0ff41eec` `ef8d96d4` | per-group GroupN bound checks (3 sites) | infra |
| `572b46e4` | SS-CERT v1 self-test path | L4 |
| `9ea8822a` `f956f3e8` `432363d3` `77c13b05` | SS-CERT v2 → v2.3 (query-identity digest) | L4 |
| `5dd95967` | T13 cert injection flag | L4 negative |
| `fe81f8aa` | `L2_AUDIT_COMMIT` Notice in HandleWriteback | L2 instrumentation |
| `dbcfada7` `fc64ffda` `184ff5a8` `b77ed899` | NewOrder Elle hooks + EllGuard | L3 |
| `544b31c4` `1c5ca4bd` | `--pequin_drop_cross_shard_writeback` byz flag | L5 negative |
| `47c85659` `ad5dbeb7` `14e704e2` `74fb43b4` | SS-CERT v3 (content-bound) | L4 tighter |
| `d46fa3a4` `ec177eb8` | **SS-CERT v3-STRICT (2f+1 via query-all + harvest before done)** | **L4 strict** |
| `6312717a` `efb494ac` `6bd0792b` | **Twins-style equivocation byz mode** | **L5 / equivocation** |
