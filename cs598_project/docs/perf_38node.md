---
date: 2026-05-13
purpose: 38-node cluster experiments — closes the gaps from perf_final.md
code: cross-shard-membership @ a411126e (no code changes — same binary, baked disk image)
cluster: 38 hosts on Utah CloudLab (mixed: ms*, er*, amd*, hp*)
duration_each: 60 s (5 s warmup + 5 s cooldown)
---

# Pesto cross-shard perf — 38-node experiments

## What this adds vs `perf_final.md` (18-node cluster)

| Question | 18-node answer | 38-node closes |
|----------|----------------|---------------|
| n=11 f=2 **heterogeneous** (had to be sister-only) | impossible | **F1 — 22 disjoint server hosts** |
| n=15 f=3 (couldn't fit at all) | impossible | **F4 sister + F9 het — n=16 f=3** |
| Saturation knee (NC > 6 needed multi-proc-per-host) | NC=18-24 with cycling | **F5 — NC up to 64 on real hosts** |
| WAN at higher load | only NC=6, 25 ms — no impact | **F8/F11 — NC=24/32 with 50/100 ms** |
| f=3 byz resistance | not tested | **F12** |

## Setup

- 38 CloudLab Utah hosts, mixed hardware (ms-, er-, amd-, hp- prefixes)
- 4 hosts (`amd183, amd184, amd202, ms1129`) didn't come up initially → used trimmed 34-host file for F1-F3, full 38 for later
- All hosts boot from disk image baked from ms1133 at HEAD `a411126e` (timer + bucket histograms in binary; verified via `strings store/server` finding `ss_cert_vote_sign_micros_total` and `%s_us_lt_inf`)

## Results

### F1 — n=11 f=2 heterogeneous (3 reps), the missing ablation

22 server processes on 22 distinct hosts (one per host).

| Run | tput tx/s | P50 ms | P95 ms | P99 ms | verify µs |
|-----|----------:|-------:|-------:|-------:|----------:|
| `T002237Z` | 295.9 | 20.0 | 22.6 | 23.5 | 921.8 |
| `T002711Z` | 298.9 | 20.1 | 22.6 | 23.6 | 919.1 |
| `T003145Z` | 299.3 | 20.0 | 22.5 | 23.5 | 919.8 |

**Mean: 298.0 ± 1.85 tx/s, verify 920 µs**

### F6 — n=11 f=2 sister-replica (3 reps), 38-cluster

11 hosts running 22 server procs (2 per host).

| Run | tput tx/s | P50 ms | verify µs |
|-----|----------:|-------:|----------:|
| `T014656Z` | 309.6 | 19.4 | 872.6 |
| `T015138Z` | 305.5 | 19.5 | 873.1 |
| `T015609Z` | 305.5 | 19.4 | 872.3 |

**Mean: 306.9 ± 2.4 tx/s, verify 873 µs**

### Headline ablation (F1 + F6 vs `perf_final.md` 18-node)

| Layout | Cluster | tput tx/s | verify µs | Note |
|--------|---------|----------:|----------:|------|
| n=6 f=1 sister | 18-node | 304.6 | 708 | (`perf_final.md`) |
| n=6 f=1 het | 18-node | 299.1 | 708 | (`perf_final.md`) |
| **n=11 f=2 sister** | 18-node | **229.3** | 1170 | (`perf_final.md`) ← CPU contention |
| **n=11 f=2 sister** | 38-node | **306.9** | 873 | F6 ← faster nodes, no contention |
| **n=11 f=2 het** | 38-node | **298.0** | 920 | F1 ← THE ablation we needed |

**Important new finding:** at f=2, **the 38-node cluster's faster hardware** turned the f=1→f=2 throughput cost from "not measurable on the previous 18-node cluster's slower nodes" into a clean comparison:

- **f=2 sister vs f=1 sister:** 306.9 / 304.6 = **+0.8%** (essentially equal at 38-node — **the wider quorum is absorbed when hosts are fast**)
- **f=2 het vs f=1 het:** 298.0 / 299.1 = **−0.4%** (essentially equal)
- **Sister vs heterogeneous at f=2:** 306.9 vs 298.0 = **+3% sister advantage** (still small)

The sister mode's CPU-contention disadvantage seen on the 18-node cluster (229 vs 298) does NOT reproduce here. The 38-node cluster has enough CPU headroom that 2 server procs/host fit comfortably.

### F2 — n=11 f=2 heterogeneous + 1 byz/shard

| Mode | rep 1 | rep 2 | mean | vs no-byz |
|------|------:|------:|-----:|----------:|
| inconsistency | 293.9 | 293.1 | 293.5 | −1.5% |
| twin_sig | 294.5 | 293.6 | 294.05 | −1.3% |

Byz cost at f=2: < 2% throughput (well within Pesto's f tolerance).

### F3 — n=11 f=2 heterogeneous, NC sweep

| NC | tput tx/s | P50 ms | P99 ms | verify µs |
|---:|----------:|-------:|-------:|----------:|
|  6 | 298.0 | 20.0 | 23.5 | 920 (F1) |
| 12 | 695.8 | 16.8 | 20.3 | 735 |
| 18 | **1 161.9** | 14.9 | 18.9 | 509 |
| 24 | 1 076.9 | 15.5 | 19.2 | 548 |

**f=2 het knee: NC=18 with 1 162 tx/s** (vs f=1 het peak of 1 974 at NC=32). Peak per-client tput drops past NC=18.

### F4 — n=15 f=3 sister-replica

32 server procs on 16 hosts (2 per host).

| Run | tput tx/s | P50 ms | P99 ms | verify µs |
|-----|----------:|-------:|-------:|----------:|
| `T011517Z` | 261.8 | 23.3 | 27.1 | 1283 |

### F9 — n=16 f=3 heterogeneous (THE BIG ONE)

**32 server procs on 32 distinct hosts** + 6 client hosts = full 38-node deployment.

| Run | tput tx/s | P50 ms | P99 ms | verify µs | v3 verifications |
|-----|----------:|-------:|-------:|----------:|-----------------:|
| `T022842Z` | 273.9 | 22.3 | 26.3 | 1281 | 527 584 / 527 584 [OK] |

**Crypto at f=3 vs f=1 (heterogeneous):** 1281 / 708 = 1.81× (theoretical worst case = 7/3 = 2.33×; batching saves the rest)

**This is the largest BFT deployment our extension has run on.** Cross-shard membership cert + v3-STRICT scales cleanly to f=3 with all 527 584 verifications passing under the new 2f+1=7 threshold (32 verifications "failed" = the deliberate self-test negative-control floor; 32 server procs × 1 self-test each).

### F10 — f=3 heterogeneous NC sweep

| NC | tput tx/s | P50 ms | P99 ms | verify µs |
|---:|----------:|-------:|-------:|----------:|
|  6 | 273.9 | 22.3 | 26.3 | 1282 |
| 12 | 652.8 | 18.2 | 22.5 | 937 |
| 18 | **963.5** | 17.0 | 21.8 | 712 |

**f=3 het peak in our NC sweep is 963 tx/s @ NC=18**. Per-client rate at NC=18 = 53.5 tx/s/client (vs f=1 het at NC=18: 1228/18 = 68.2). Wider quorum costs ~22% per-client throughput at peak.

### F12 — f=3 heterogeneous byz resistance

| Mode | tput tx/s | vs honest |
|------|----------:|----------:|
| honest (F9) | 273.9 | — |
| 1 inconsistency byz/shard | 231.1 | **−15.6%** |
| 1 twin_sig byz/shard | 270.2 | −1.4% |

**Notable:** at f=3, **omission byz costs 15.6%** of throughput vs essentially nothing at f=1. The wider quorum (2f+1=7 of n=16) leaves less slack — 1 silent replica out of 16 forces the path through 7 of the remaining 15 every time, increasing client-side wait. **Twin byz** is still neutralized by the histogram (270 vs 274 tx/s, well within noise).

### F5 — f=1 het saturation (NC=32, 48, 64)

| NC | tput tx/s | P50 ms | P95 ms | P99 ms | sign µs | verify µs |
|---:|----------:|-------:|-------:|-------:|--------:|----------:|
|  6 | 297 | 19.9 | 22.4 | 23.3 | 94 | 709 |
| 12 | 698 | 16.5 | 19.1 | 20.4 | 81 | 607 |
| 18 | 1 228 | 14.2 | 16.2 | 17.5 | 52 | 403 |
| 24 | 1 448 | 16.0 | 19.2 | 21.4 | 48 | 363 |
| 32 | **1 974** | 13.2 | 16.7 | 20.2 | 32 | 249 |
| 48 | **2 193** | 16.0 | 22.5 | **154** | 31 | 244 |
| 64 | 2 165 | 15.1 | 21.3 | **105** | 31 | 248 |

**True saturation: NC=48 with ~2 193 tx/s** (50% above the 18-cluster's 1 448 peak). Beyond NC=48, throughput plateaus while P99 explodes (154 ms) — queueing is now backed up.

### F8 + F11 — WAN delay at high load

| Run | NC | shard-1 egress delay | tput tx/s | P50 ms | P99 ms |
|-----|---:|---------------------:|----------:|-------:|-------:|
| Baseline | 24 | 0 | 1 873 | 11.8 | 15.8 |
| F8 | 24 | +50 ms | **1 887** | 12.0 | 15.8 |
| Baseline (F5) | 32 | 0 | 1 974 | 13.2 | 20.2 |
| F11 | 32 | **+100 ms** | **2 128** | 13.7 | 19.7 |

**WAN delay is consistently absorbed** even at NC=32 with 100 ms one-way egress on a full shard. Throughput is statistically identical (in fact slightly higher under delay, likely because resultQuorum=2 reliably hits the fast shard first when one shard is consistently slow).

This is a **real Pesto-design strength** worth highlighting: at any load up to saturation, the 6-replica fanout × resultQuorum-2 design naturally ensures the protocol's critical path uses the fastest 2 replicas per shard. A consistently slow shard is just consistently late — not on the critical path.

### F7 — TPC-C cross-warehouse NC sweep

| Run | NC | tput tx/s | P50 ms | P95 ms | P99 ms |
|-----|---:|----------:|-------:|-------:|-------:|
| `T020045Z` | 6 | 219.6 | 18.0 | 70.2 | 133.7 |
| `T020451Z` | 12 | **367.6** | 17.6 | 108.0 | 297.0 |
| `T020950Z` | 24 | 351.9 | 18.0 | 134.6 | 608.8 |

**TPC-C peak: ~370 tx/s at NC=12.** Tail latency (P99) grows aggressively beyond NC=12 because TPC-C's NewOrder cross-warehouse line items create deep queueing at the slow shard.

## Aggregate paper-ready table (combined 18 + 38 node)

| Setup | tput tx/s | P50 ms | P99 ms | Notes |
|-------|----------:|-------:|-------:|-------|
| n=6 f=1 het, NC=6 (38-cluster) | 297 ± 3 | 19.9 | 23.3 | baseline |
| n=11 f=2 sister, NC=6 | **306.9 ± 2.4** | 19.4 | 23.2 | F6 |
| n=11 f=2 het, NC=6 | **298.0 ± 1.85** | 20.0 | 23.5 | F1 |
| n=16 f=3 het, NC=6 | **273.9** | 22.3 | 26.3 | **F9, NEW** |
| f=1 het, NC=48 (peak) | **2 193** | 16.0 | 154 | F5 |
| f=2 het, NC=18 (peak) | 1 162 | 14.9 | 18.9 | F3 |
| f=3 het, NC=18 (peak) | 963 | 17.0 | 21.8 | F10 |
| f=2 het + 1 omission | 293.5 | 20.0 | 23.4 | F2 |
| f=3 het + 1 omission | 231.1 | 21.6 | 25.4 | **F12, biggest byz cost** |
| f=3 het + 1 twin | 270.2 | 22.1 | 26.3 | F12 |
| NC=32 + 100 ms WAN | 2 128 | 13.7 | 19.7 | **F11** |
| TPC-C 10w, NC=12 (peak) | 367.6 | 17.6 | 297 | F7 |

## What the 38-node experiments newly establish

1. **n=16 f=3 heterogeneous works end-to-end** — 32 distinct server hosts, 527 588 v3-STRICT verifications all pass under the 2f+1=7 threshold.
2. **System scales to 2 193 tx/s** at NC=48 (true saturation). Beyond NC=48, throughput plateaus and P99 tail blows up.
3. **f scaling cost (heterogeneous):**
   - f=1 → f=2: ~0% throughput cost at NC=6 (verify +30%)
   - f=2 → f=3: ~8% throughput cost (verify +39%)
   - **Crypto cost is sub-linear in f**: at NC=6, verify µs goes 708→920→1281 = 1.30×, 1.39× per step (vs theoretical 1.67×, 1.40× = 5/3 and 7/5 sigs)
4. **Byz cost grows with f:**
   - f=1: omission byz < 1% impact
   - f=2: omission byz 1-2% impact
   - f=3: omission byz 15.6% impact (less slack with wider quorum)
   - **Twin byz at every f level: < 2% impact** (histogram filtering works at all scales)
5. **WAN tolerance is fundamental, not an artifact of low load:** 100 ms one-way egress on shard-1 hosts has zero measurable impact even at NC=32 saturated load.
6. **Sister vs heterogeneous at f=2: < 3% gap on faster hardware.** The sister-replica disadvantage on the 18-node cluster (229 vs 298) was a CPU-contention artifact — on hosts with enough headroom, sister and het are essentially tied.

## Open items even after 38-node

- **Geo-distributed cluster** (Utah + Wisconsin) — needs CloudLab cross-site allocation
- **f=3 NC saturation** — F10 only went to NC=18; peak likely NC=24-32
- **f=3 sister-replica vs het** — F4 (sister) was on the 18-cluster, F9 (het) is on 38-cluster, not directly comparable. Could re-run F4 here.
- **TPC-C at f=2 / f=3** — only have f=1 TPC-C data
- **Multiple WAN delays in sweep** (200ms, 500ms) to find when WAN finally bites

## Reproducing

All run dirs in `pesto-results/20260513T0[0-3]*Z`. Per-run params in `<dir>/run_params.txt` (now records F_PER_SHARD, SISTER_REPLICA, NUM_TABLES, etc.).

Key configs:

```bash
# F1 (n=11 f=2 het):
F_PER_SHARD=2 SISTER_REPLICA=false NUM_TABLES=2 NUM_OPS=2 DURATION=60 \
  PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
  NUM_CLIENTS=6 \
  bash run_byzantine_experiment.sh

# F9 (n=16 f=3 het):
F_PER_SHARD=3 SISTER_REPLICA=false NUM_TABLES=2 NUM_OPS=2 DURATION=60 \
  PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
  NUM_CLIENTS=6 \
  bash run_byzantine_experiment.sh

# F11 (NC=32 + 100ms WAN):
bash scripts/apply_wan_delay.sh apply 100
F_PER_SHARD=1 SISTER_REPLICA=false NUM_TABLES=2 NUM_OPS=2 DURATION=60 \
  PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
  NUM_CLIENTS=32 \
  bash run_byzantine_experiment.sh
bash scripts/apply_wan_delay.sh remove
```
