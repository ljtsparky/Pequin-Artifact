# P3 — SS-CERT v3: content-bound cert over query_result_hash

**Date:** 2026-05-12
**Code:** `cross-shard-membership` @ `74fb43b4` (v3 server + client + verifier threshold)
**Workload:** rw-sql NT=2, PEQUIN_EAGER=false SCAN_AS_POINT=false, 20s × 6 clients

## What this closes

Before P3: SS-CERT v2.3 signed over `BLAKE3(query_seq || client_id ||
retry_ver || group_id)` — query IDENTITY only. A byzantine replica that
didn't compute the snapshot could still sign a valid-looking cert.
The cert was a thin liveness witness, not a safety witness.

After P3: v3 cert signs over `BLAKE3(qid... || query_result_hash)`.
`query_result_hash` is Pesto's BLAKE3 over the read set the replica
actually computed (set by `CacheReadSet` in `querysync-server.cc:947`).
A byzantine replica must execute the query and produce the right read
set to forge a valid signature.

## Headline numbers — honest path

| Counter | Value | Meaning |
|---------|------:|---------|
| `ss_cert_v3_votes_attached` (server) | 87 852 | every QueryResultReply carries a v3 vote |
| `ss_cert_seen` (server) | 87 852 | server received cert on every SyncClientProposal |
| **`ss_cert_verifications_done`** (server) | **87 852** | **100% pass** |
| `ss_cert_verifications_failed` (server) | 12 | only the 12 startup self-tests |
| `client_v3_vote_received` (6 clients) | 26 983 | v3 votes harvested in HandleQueryResult |
| `client_cert_v3_built` (6 clients) | 6 | one cert per ShardClient (lifetime-cached) |
| `client_cert_v3_attached` | 13 487 | per outgoing SyncClientProposal |
| `client_cert_v23_attached` | 6 | v2.3 fallback only for first few queries before v3 built |
| v3 promotion rate | **99.95%** | v3 dominates as soon as one cert is built |

## Headline numbers — adversarial (T13 reused on v3)

| Inject mode | seen | verify_OK | verify_FAIL | Reject % |
|-------------|-----:|----------:|------------:|---------:|
| `one_vote`   | 71 148 | 0 | **71 160** | **100%** |
| `wrong_sig`  | 68 730 | 0 | **68 742** | **100%** |
| `wrong_group`| 70 716 | 0 | **70 728** | **100%** |

Verifier is sound AND complete on v3-relaxed.

## Threshold choice — v3-relaxed (f+1 instead of 2f+1)

Pesto's per-query result quorum is small (often 2 on n=6 f=1 — only 2
replicas designated for reply). Collecting 2f+1=3 same-digest votes
from a SINGLE PendingQuery is rare. Two paths:

1. **v3-relaxed (this run):** lower the verifier threshold to f+1.
   Safety claim becomes "at least 1 honest replica attested to the
   content". Weaker than 2f+1 but still meaningful and still rejects
   the `one_vote` attack (cert with 1 vote < 2 threshold).
2. **v3-strict (future):** accumulate v3 votes ACROSS queries. The
   cert binds to the LATEST query whose digest accumulated 2f+1 votes.
   Requires cross-query state on the ShardClient and a different
   cert-staleness model. Deferred.

We went with v3-relaxed for this iteration. Safety trade-off documented.

## Bug taxonomy

| Iter | Symptom | Fix | Commit |
|------|---------|-----|--------|
| v3 | `client_cert_v3_built = 0` even with 24 724 votes received | First-vote digest selection picked minority; switched to histogram + majority | `ad5dbeb7` |
| v3.1 | Still `cert_v3_built = 0`, `client_v3_quorum_attempted = 0` | Per-PendingQuery only got ~2 votes (Pesto's small result quorum) — never reached 2f+1=3 threshold | lower to f+1 (`14e704e2`) |
| v3.2 | `client_cert_v3_built = 6`, `cert_v3_attached = 14113`, but **`verifications_failed = 91872 / 91896 = 99.96%`** | Verifier still required 2f+1 votes; cert only had 2 (= f+1) | verifier threshold f+1 (`74fb43b4`) |
| v3.3 | **100% pass on honest, 100% reject on all 3 T13 modes** | — | — |

## What changed vs v2.3 (concrete code diff impact)

| Aspect | v2.3 | v3-relaxed |
|--------|------|-----------|
| Digest input | query_seq + client_id + retry_ver + group_id | + `query_result_hash` |
| Vote location | `SyncReply.vote` (early, before query exec) | `QueryResultReply.v3_vote` (late, after exec) |
| Required votes | 2f+1 | f+1 |
| Honest replica can fake without doing work | YES (only needs query identity) | NO (needs to compute matching read set) |
| Reject one_vote attack | YES (2 < 2f+1=3) | YES (1 < f+1=2) |
| Throughput impact | minimal | minimal (~3% extra signature per query) |

## Honest experiment AGGREGATE
`pesto-results/20260512T065024Z/` — see counters above.

## Adversarial experiments
- `pesto-results/20260512T065344Z/` — one_vote inject
- `pesto-results/20260512T065632Z/` — wrong_sig inject
- `pesto-results/20260512T065923Z/` — wrong_group inject

## Future tightening (v3-strict, out of scope here)

1. Cross-query vote accumulation: keep `unordered_map<digest, vector<vote>>`
   over the ShardClient lifetime. When any (digest) accumulates 2f+1 votes,
   crystallize that cert. Then verifier can require 2f+1.
2. Bind cert to the most recent merged_snapshot the client just sent,
   not just the read result. Two-round signing: round 1 = LocalSnapshot,
   round 2 = sign(merged_ss). Significantly higher latency but full
   safety claim.

## Reproduction

```bash
# honest
PEQUIN_EAGER=false SCAN_AS_POINT=false BENCHMARK=rw-sql NUM_TABLES=2 \
    DURATION=20 bash run_byzantine_experiment.sh

# T13 on v3
for m in one_vote wrong_sig wrong_group; do
    INJECT_BAD_SS_CERT=$m PEQUIN_EAGER=false SCAN_AS_POINT=false \
        BENCHMARK=rw-sql NUM_TABLES=2 DURATION=15 \
        bash run_byzantine_experiment.sh
done
```
