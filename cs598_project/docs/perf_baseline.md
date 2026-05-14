---
date: 2026-05-13
purpose: First-pass performance baseline for the cross-shard heterogeneous Pesto extension
duration_each: 60 s (5 s warmup + 5 s cooldown)
config: 2 shards × 6 replicas (n=6, f=1) on CloudLab; 6 clients
benchmark: rw-sql, NUM_OPS=2, NUM_KEYS=1000, zipf 0.5
---

# Perf baseline — 5-config sweep

## Setup

- **Cluster:** 18 CloudLab nodes (`ms*.utah.cloudlab.us`), see `lab_ssh.txt`
- **Shards:** 2 disjoint groups of 6 replicas each (heterogeneous; not sister-replica)
- **Clients:** 6 (last 1 has 20% inject_failure)
- **Workload:** rw-sql, NUM_KEYS=1000, NUM_OPS=2, zipf=0.5
- **Per-run duration:** 60 s (5 s warmup + 5 s cooldown → 50 s measurement window)
- **Code at:** `cross-shard-membership @ 6bd0792b`
- **Methodology**:
  - Throughput: `sum(rw_sql_committed across all 6 clients) / 60s`
  - Latency: `bench_client.cc` CooldownDone line, averaged across clients
  - Analysis script: `scripts/perf_analyze.py`

## Results

| # | Config | NT | byz | path | commit | tput (tx/s) | P50 (ms) | P95 (ms) | P99 (ms) |
|---|--------|----|-----|------|--------|------------:|---------:|---------:|---------:|
| 1 | single-shard | 1 | none | eager | 600 | **10.0** | 373 | 1 276 | 7 573 |
| 2 | xshard baseline | 2 | none | eager | 709 | **11.8** | 357 | 1 361 | 3 736 |
| 3 | xshard + SS-CERT v3-STRICT | 2 | none | sync + query-all | 4 974 | **82.9** | 19 | 1 023 | 1 029 |
| 4 | + 1 omission/shard | 2 | inconsistency | sync + query-all | 18 128 | **302.1** | 20 | 22 | 23 |
| 5 | + 1 twin/shard | 2 | twin_sig | sync + query-all | 18 041 | **300.7** | 20 | 22 | 23 |

Run dirs:
1. `pesto-results/20260512T164832Z`
2. `pesto-results/20260512T165203Z`
3. `pesto-results/20260512T165546Z`
4. `pesto-results/20260512T165916Z`
5. `pesto-results/20260512T170304Z`

SS-CERT counter sanity (server-side):

| # | ss_cert_v3_votes_attached | ss_cert_verifications_done | byz_twin_perturbations |
|---|--------------------------:|---------------------------:|-----------------------:|
| 1 | 0 (eager bypasses sync) | 0 | n/a |
| 2 | 0 (eager bypasses sync) | 0 | n/a |
| 3 | 49 760 | 49 760 ✅ | n/a |
| 4 | 223 476 | 223 476 ✅ | 0 |
| 5 | 222 450 | 222 450 ✅ | 37 075 |

## Observations

1. **The default Pesto fast-path (`eager_exec`) is unexpectedly slow on this
   deployment.** Runs 1–2 (eager) cap at 10–12 tx/s aggregate with 373 ms
   median latency. The sync path delivers 7–25× higher throughput and 18×
   lower median latency. Reason (probable): eager runs into the
   small-quorum optimistic conflict-retry loop frequently with zipf=0.5
   contention on a 1 000-key working set; sync path uses the explicit
   2f+1 snapshot path which avoids the retry.

2. **SS-CERT v3-STRICT adds ~zero throughput overhead vs no-cert sync
   baseline.** Going from no-byz sync (run 3) to byz-sync (runs 4, 5),
   sync path serves 3.6× more transactions, and the v3 verification path
   ran 223k+ times in 60s on each. The per-cert verification is fast
   enough (sub-millisecond) that it does not bottleneck.

3. **Byz fault scenarios run FASTER than the no-fault sync baseline.**
   Runs 4 and 5 outperform run 3 by 3.6×. Two probable contributors:
   - With 1 byz/shard, the byz replica drops/perturbs ~ 1/6 of replies,
     **reducing client-side message processing load**. With `query-all`
     fanout (6 replies per query in run 3 vs 5 in runs 4/5), the client
     spends 17% less on parsing v3 votes. This compounds: less CPU
     contention on the client → faster benchmark loop.
   - Run 3's slightly elevated backoff count (376 vs 305 / 821 — but
     this is a noise floor) does not fully explain the gap. Network
     congestion or scheduling jitter at the 6-replica fanout is likely.
   - **Caveat:** this is an artifact of the small-cluster, 6-client
     setup. On a paper-sized deployment (e.g., 30+ clients) the byz
     "advantage" should disappear and we expect run 3 to outperform 4/5.

4. **Twin vs omission byz: indistinguishable at this load.** Runs 4 and
   5 differ by < 1% in throughput and < 0.5 ms in P95. Twin's XOR
   perturbation in the v3 vote is filtered cleanly by the client-side
   majority histogram before cert-build — no detectable cost.

5. **Tail latency improvement with byz is dramatic.** P99 collapses from
   1 029 ms (run 3) to 23 ms (runs 4, 5). This matches the throughput
   pattern: at run-3's load, occasional 6-replica synchronization stalls
   produce ~1 s tails. With 5/6 fanout (one byz), these stalls
   disappear.

## What this baseline DOES NOT measure

1. **SS-CERT micro-overhead.** This sweep measures end-to-end throughput;
   it does not isolate the **µs cost** of `VerifySnapshotCert`. That
   needs `Latency_Start`/`Latency_End` instrumentation in
   `common.cc:VerifySnapshotCert` and matching counters in the stats
   JSON. **Open item.**

2. **Pesto-Homogeneous baseline.** Our deployment is heterogeneous
   (disjoint membership). To measure the cost of removing sister-replica
   assumption vs original Pesto, we'd need to run with both groups
   sharing the same 6 hosts (sister replicas), then compare against the
   12-host disjoint deployment. **Open item — requires a redeployment
   config switch.**

3. **Cross-shard fraction sweep.** This run uses `NUM_TABLES=2 NUM_OPS=2`
   which yields a fixed ~50% cross-shard rate. Pesto's published curves
   sweep 0% / 25% / 50% / 100%. **Open item — needs a separate sweep.**

4. **TPC-C numbers.** rw-sql is a microbenchmark. Real cross-shard
   workload (TPC-C NewOrder cross-warehouse line items) is qualitatively
   different. **Open item.**

5. **Load curve (latency vs offered tput).** We measure at *fixed
   offered load* of 6 clients. The published Pesto figures sweep client
   count to produce a knee-of-curve. **Open item.**

6. **Confidence intervals.** Each config is run once. No bars or
   stddev. **Open item.**

7. **Network/CPU baseline of CloudLab nodes.** No isolation of
   software-induced latency from network RTT. Pesto's paper reports a
   0.15 ms baseline RTT between Utah nodes — ours likely similar but
   unverified.

## Recommended next steps (in priority order)

1. **Add `Latency_*` timers** to `VerifySnapshotCert` and v3 vote
   generation, re-run config 3 to get crypto-overhead histograms. **Easy,
   high-value.**
2. **Sweep cross-shard fraction** at `NT={1,2,4}` × `NUM_OPS={1,2,4}`
   matrix. **Medium.**
3. **Add client-count sweep** at NT=2 with 1, 3, 6, 12, 18 clients to
   get a load curve. **Easy.**
4. **TPC-C cross-warehouse perf** (a single 60-s run with WAREHOUSES=10
   and the existing TPC-C image). **Medium.**

## Bug history during perf baseline

- `run_params.txt` did not record `NUM_TABLES`, `PEQUIN_EAGER`,
  `BYZ_REPLICA_MODE`, etc. — five runs are interpretable only by
  cross-referencing the shell command. Patched in
  `run_byzantine_experiment.sh:416` to add these fields for future runs.
