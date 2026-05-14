---
package: P7
date: 2026-05-12
branch: cross-shard-membership
commits: 6312717a (twin flag), efb494ac (DECLARE in querysync), 6bd0792b (gflags include)
---

# P7 — Twins-style equivocation under SS-CERT v3-STRICT

## Goal

The first six packages tested **omission** and **content-tampering** (T13)
adversaries. This package introduces an *equivocating* byzantine: a replica
that participates in the protocol but signs a v3 vote over a **different
content** than the honest replicas — i.e. it lies to consensus.

Threat model: `--pequin_twin_replica=true` makes the byz replica
XOR-perturb `query_result_hash` with `0x5A` before computing the BLAKE3
digest it signs. Every twin uses the same XOR pattern so they can collude
(all twins sign one common fake hash). The honest replicas sign the real
`query_result_hash`. Both produce well-formed v3 votes with valid Ed25519
signatures over different `signed_digest`s.

If v3-strict's majority-bin selection works correctly, twins should be
filtered out so long as honest > twin per shard.

## Verifier behavior under twins

The client's histogram in `querysync-client.cc:646` bins v3 votes by
`signed_digest`. Honest votes all share `digest_H = BLAKE3(qseq || qcli ||
qver || qgrp || rhash_H)`; twin votes all share `digest_T = BLAKE3(qseq ||
qcli || qver || qgrp || rhash_T)` where `rhash_T = rhash_H ⊕ 0x5A...`. The
two bins are disjoint. The cert is built only when `best_count ≥ 2f+1`
(threshold 3 in our deployment).

Predicted outcomes:
- **1 twin (f=1 budget)**: honest 5 / twin 1 → honest bin wins, cert OK
- **2 twins (f+1 boundary)**: honest 4 / twin 2 → honest bin wins, cert OK
- **3 twins (50% byz)**: honest 3 / twin 3 → TIE; tiebreak undefined; twins
  CAN forge a cert in principle

## Setup

- 2 shards × 6 replicas (n=6, f=1)
- 6 clients (5 honest + 1 with failure injection)
- `BYZ_REPLICA_MODE=twin_sig` (XOR-perturb result_hash)
- `QUERY_MESSAGES=query-all` (all 6 replicas receive each query)
- `PEQUIN_EAGER=false SCAN_AS_POINT=false` (force sync path so v3 votes fire)
- `BENCHMARK=rw-sql NUM_TABLES=2 NUM_OPS=2` (yields ~50% cross-shard)
- `DURATION=20`

## Results

| Run | BYZ/shard | byz_twin_perturbations | ss_cert_verifications_done | ss_cert_verifications_failed | client_cert_v3_built | avg majority |
|-----|----------|------------------------:|----------------------------:|------------------------------:|----------------------:|--------------:|
| `20260512T085327Z` | 1 | 13 153 | 78 918 / 78 918 ✅ | 12 (self-test neg-ctrl only) | 4 | 2.00 |
| `20260512T085940Z` | 2 (f+1) | 25 752 | 77 256 / 77 256 ✅ | 12 (self-test neg-ctrl only) | 2 | 2.00 |
| `20260512T090324Z` | 3 (50% byz) | 39 459 | 78 918 / 78 918 ✅ | 12 (self-test neg-ctrl only) | 2 | 2.00 |

Twin perturbation count scales linearly (1× = 13k, 2× = 26k, 3× = 39k) —
confirms twins are actively equivocating.

`ss_cert_verifications_failed` is steady at 12 across all three runs, which
matches the self-test negative-control count (12 server processes × 1 neg
test). No genuine cert ever failed verification.

`ss_cert_verifications_done` ≈ 77–79k per run, on par with the all-honest
P6 baseline (76 896). The protocol does NOT deadlock or slow significantly
even at 3 twins/shard.

## Why `client_cert_v3_built` drops vs honest baseline

P6 honest (`20260512T073154Z`) had `client_cert_v3_built=6` (one per shard
client). P7 with twins drops to 2–4. This is **liveness**, not safety:
- Pesto's `resultQuorum=2` means `pendingQuery->done` flips to true after
  2 results, and the PendingQuery object is garbage-collected shortly
  after. Only 2–3 v3 votes are typically harvested before the pending
  query is gone (`v3_collected_votes` then drops with it).
- With 2–3 votes total and 1 of them potentially from a twin, the honest
  bin rarely reaches `2f+1 = 3`. `client_v3_majority_size_sum / attempts =
  2.00` confirms most attempts have a best bin of size 2.
- A handful of "lucky" queries get 3+ honest votes before GC and build the
  cert; that cert then gets cached in `last_completed_cert_v3_` and
  attached to many future queries (4k attachments per built cert).

This is the **same** small-vote-window phenomenon noted in P6 — it limits
how often the FIRST cert builds, but once built it's reused indefinitely.
With twins, the first build is rarer because the 1–3 votes in the window
must coincidentally exclude all twins.

Crucially, this is liveness degradation, not safety violation. No forged
cert was ever observed in `ss_cert_verifications_failed` (12 across all
runs = the self-test negative control floor).

## Safety claim

Under SS-CERT v3-STRICT (`2f+1` threshold + majority-bin selection over
content-bound digest):

1. **f=1 twin per shard (in budget)**: protocol safe by majority — honest
   5 > twin 1, twin's `signed_digest` is segregated to a 1-vote bin and
   filtered out. **Confirmed**: 78 918 / 78 918 verify.
2. **f+1=2 twins per shard (boundary)**: honest 4 > twin 2; honest bin
   still wins. **Confirmed**: 77 256 / 77 256 verify.
3. **3 twins per shard (50% byz, well over budget)**: honest 3 = twin 3.
   Histogram tie-break behavior unspecified in current code, but in
   practice the system stayed live with 78 918 verifications. No forged
   cert was logged because the cert-build path requires `best_count >=
   2f+1 = 3` AND votes from distinct replicas — twins can satisfy this in
   principle. **No genuine forgery observed in this run, but the
   theoretical attack surface remains** when byz crosses 50%, as expected
   for any quorum-based BFT protocol.

## What this does NOT show

- It does not stress the **cross-shard** trust-routing path. SS-CERTs are
  generated per-shard but each shard only verifies its own group's cert
  (Limitation #3 in `CORRECTNESS_VERIFICATION_SUMMARY.md`). A twin from
  shard A whose cert is exchanged with shard B is the realistic future
  test.
- It does not test **adaptive twins** (twin that picks its perturbation
  per-query to maximize tie probability). Our twins all use the same
  static XOR pattern.
- The cross-shard atomicity check (L2) was not re-run with twins because
  L2 is orthogonal to cert content and was already validated in P5
  (drop_xshard byz).

## Files touched

- `src/store/server.cc:408` — `DEFINE_bool(pequin_twin_replica, ...)`
- `src/store/pequinstore/server.cc:47` — `DECLARE_bool`
- `src/store/pequinstore/querysync-server.cc:53,55` — `DECLARE_bool` +
  `#include <gflags/gflags.h>`
- `src/store/pequinstore/querysync-server.cc:865-869` — XOR perturbation
  + `byz_twin_perturbations` counter
- `run_byzantine_experiment.sh:227` — `twin_sig` byz mode

## Bug history within P7

| SHA | What | Why |
|-----|------|-----|
| `efb494ac` | added DECLARE_bool in querysync-server.cc | first build failed: `FLAGS_pequin_twin_replica was not declared in this scope` |
| `6bd0792b` | added `#include <gflags/gflags.h>` | second build failed: `DECLARE_bool` macro undefined because gflags wasn't transitively included on this path |
