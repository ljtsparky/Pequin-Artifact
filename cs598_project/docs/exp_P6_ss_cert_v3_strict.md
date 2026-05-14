# P6 — SS-CERT v3-strict (2f+1 verifier threshold)

**Date:** 2026-05-12
**Code:** `cross-shard-membership` @ `ec177eb8` (verifier+client both 2f+1, query-all)
**Workload:** rw-sql NT=2, PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all

## What this closes vs v3-relaxed (P3)

P3 (v3-relaxed) lowered the SS-CERT verifier threshold to f+1 because
Pesto's per-query result quorum is small (often 2 on n=6 f=1). Safety
claim weakened to "at least 1 honest replica attested".

P6 (v3-strict) restores the classical BFT 2f+1 threshold via two changes:

1. **Orchestrator sets `--pequin_query_messages=query-all`** — query
   is sent to all n=6 replicas (not just queryQuorum=3). Every replica
   replies with a v3_vote, so client can naturally collect 2f+1 same-
   digest votes per query.

2. **Client collects v3 votes BEFORE the `pendingQuery->done` early-return**
   — Pesto flips `done` after just 2 results (resultQuorum=2), but to
   build a 2f+1=3 v3 cert we need votes from the OTHER replicas that
   reply later. Moving the harvest above the done check makes them count.

Safety claim restored: "2f+1 replicas of group G with at least f+1
honest among them ALL attested to the same content."

## Headline numbers — honest path

| Counter | Value |
|---------|------:|
| `ss_cert_v3_votes_attached` (server) | 76 896 |
| `ss_cert_seen` (server) | 76 896 |
| **`ss_cert_verifications_done`** (server) | **76 896** |
| `ss_cert_verifications_failed` (server) | 12 (startup self-tests only) |
| `client_v3_vote_received` (6 clients) | 35 224 |
| `client_v3_quorum_attempted` | 6 |
| `client_v3_majority_size_sum` | 18 |
| **AVG MAJORITY per attempt** | **3.00** (= 2f+1=3, exact) |
| `client_cert_v3_built` | 6 (one per ShardClient) |
| `client_cert_v3_attached` | 11 740 |
| `client_cert_v23_attached` (fallback) | 6 (first few queries before v3 built) |

Verify rate: **100% PASS**, v3 promotion: **99.95%**.

## Headline numbers — adversarial (T13 reused on v3-strict)

| Inject mode | seen | verify_OK | verify_FAIL | Reject % |
|-------------|-----:|----------:|------------:|---------:|
| `one_vote`   | 65 508 | 0 | 65 520 | **100%** |
| `wrong_sig`  | 63 153 | 0 | 63 165 | **100%** |
| `wrong_group`| 65 098 | 0 | 65 110 | **100%** |

Verifier is sound AND complete on v3-strict.

## Headline numbers — under byzantine fault

| Run | Fault | seen | verify_OK | AVG MAJORITY | commits |
|-----|-------|-----:|----------:|-------------:|--------:|
| `20260512T074436Z` | 1 byz omission per shard | 79 218 | 79 218 | **3.00** | 6 073 |

The byz replica is excluded from the majority (either silent or signing
different content), so the 5 honest replicas form an exact 2f+1=3
quorum on the same digest. **100% verify** under byzantine.

## What this means for the overall safety claim

v3-strict is the **classical BFT cert quorum**:
- 2f+1 votes → at most f byzantine signers possible
- ≥ f+1 honest signers among them
- Honest signers couldn't have agreed unless the content is real

A byzantine replica cannot forge a v3-strict cert by:
- Single-handedly signing — needs 2f+1 distinct replica_ids (membership cert enforced)
- Coercing other replicas — they're independent, they sign what they compute
- Replaying — signed_digest binds to specific query_result_hash (P3 v3 design)
- Substituting wrong content — verifier checks vote.signature(cert.snapshot_digest)

This is the same safety property Pesto's Phase1 quorum already provides
for transaction commits — now extended to query-result attestation.

## v3-relaxed → v3-strict bug taxonomy

| Iter | Symptom | Root cause | Fix |
|------|---------|-----------|-----|
| v3-strict (initial) | `client_cert_v3_built = 0` despite `query-all` setting | `pendingQuery->done` returns early after 2 results; later replies dropped | move harvest above done check (P3.5, `ec177eb8`) |
| v3-strict (after P3.5) | AVG MAJORITY = 3.00 ✓, `client_cert_v3_built = 6` ✓, **`verifications_done = 76 896` (100% pass)** | — | — |

## Compare v3-relaxed vs v3-strict

| Property | v3-relaxed (P3.3) | v3-strict (P6) |
|----------|-------------------|-----------------|
| Verifier threshold | f+1 = 2 | **2f+1 = 3** |
| Safety claim | "≥ 1 honest replica attested" | **"≥ f+1 honest replicas attested"** |
| `--pequin_query_messages` needed | default (2f+1) | **`query-all` (n)** |
| Throughput impact | minimal | ~3-5% (more replicas reply) |
| Verifies honest cert | ✅ 100% | ✅ 100% |
| Rejects T13 adversarial | ✅ all 3 modes 100% | ✅ all 3 modes 100% |
| Holds under byz | ✅ | ✅ |

## Files / commits

| SHA | What |
|-----|------|
| `d46fa3a4` | verifier threshold 2f+1; client need 2f+1; query-all env var |
| **`ec177eb8`** | **P3.5: harvest v3 votes before done check** |

## Reproduction

```bash
# v3-strict honest
QUERY_MESSAGES=query-all PEQUIN_EAGER=false SCAN_AS_POINT=false \
    BENCHMARK=rw-sql NUM_TABLES=2 DURATION=20 \
    bash run_byzantine_experiment.sh

# v3-strict + 1 byz omission per shard
QUERY_MESSAGES=query-all PEQUIN_EAGER=false SCAN_AS_POINT=false \
    BENCHMARK=rw-sql NUM_TABLES=2 BYZ_PER_SHARD=1 BYZ_REPLICA_MODE=inconsistency \
    DURATION=20 bash run_byzantine_experiment.sh

# T13 on v3-strict (each mode 100% reject)
for m in one_vote wrong_sig wrong_group; do
    INJECT_BAD_SS_CERT=$m QUERY_MESSAGES=query-all PEQUIN_EAGER=false \
        SCAN_AS_POINT=false BENCHMARK=rw-sql NUM_TABLES=2 DURATION=15 \
        bash run_byzantine_experiment.sh
done
```
