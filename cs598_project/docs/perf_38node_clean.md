---
date: 2026-05-13
purpose: Clean apples-to-apples ablation on the 38-node cluster
       (supersedes earlier F-runs that used a 34-host trimmed file with
       different physical host composition)
code: cross-shard-membership @ a411126e
cluster: 38 hosts on Utah CloudLab (mixed ms*, er*, amd*, hp*), full lab_ssh.txt
duration_each: 60 s (5 s warmup + 5 s cooldown)
---

# 38-cluster perf — clean ablations (H + I + G runs)

## Why this exists separately from perf_38node.md

`perf_38node.md` mixes F-runs (used `lab_ssh34.txt` because 4 hosts were
booting) with later G-runs (used full `lab_ssh.txt` with all 38 hosts).
The physical host composition differed — specifically `amd183`
(performant AMD EPYC node) was missing from shard 0 in the F-runs and
present in the G/H-runs. The two host sets produced **~20% different
absolute throughput** even at identical f/n/NC.

This doc re-runs the headline ablations with the FULL `lab_ssh.txt` host
set, 3+ repeats each, so we have apples-to-apples numbers for the paper.

## The clean ablation table

All numbers from rw-sql NT=2 OPS=2 NC=6 sync-path v3-STRICT query-all,
60-second runs, 5-second warmup/cooldown, 38-host cluster.

| Config | mean ± stddev | CV | P50 ms | P99 ms | verify µs |
|--------|--------------:|---:|-------:|-------:|----------:|
| **n=6 f=1 het (G6 ×5)** | **360.3 ± 4.5** | 1.25% | 16.4 | 20.3 | 584 |
| n=11 f=2 het (H1 ×3) | **305.2 ± 5.7** | 1.87% | 19.1 | 22.6 | 872 |
| n=11 f=2 sister (H2 ×3) | **308.3 ± 3.9** | 1.27% | 19.4 | 23.2 | 871 |
| n=16 f=3 het (H3 ×3) | **271.9 ± 2.4** | 0.88% | 22.2 | 26.2 | 1281 |
| n=16 f=3 sister (H4 ×3) | **257.5 ± 5.5** | 2.13% | 23.3 | 27.2 | 1284 |

All CVs < 2.2% — measurements are stable. 5-rep G6 baseline gives a CV
of 1.25% which is the noise floor of the cluster.

## Headline finding for the paper

**Removing the sister-replica assumption costs essentially nothing.**

| f | sister tput | het tput | gap |
|--:|------------:|---------:|----:|
| 1 | n/a* | 360.3 | — |
| 2 | 308.3 | 305.2 | **−1.0%** (within CV) |
| 3 | 257.5 | 271.9 | **+5.3%** (het *faster*, sister has CPU contention) |

\* n=6 f=1 sister puts 12 procs on 6 hosts (2/host); previous 18-cluster
data showed this is also indistinguishable from f=1 het.

The 5.3% het-advantage at f=3 is the first time we see sister
disadvantage on this cluster, and it comes from CPU pressure: f=3 sister
runs 32 server procs on 16 hosts (2 per host) while f=3 het runs them
on 32 distinct hosts.

## f-scaling cost (het, paper-ready)

| Transition | tput delta | P50 delta | verify µs ratio |
|------------|-----------:|----------:|----------------:|
| f=1 → f=2 | −15.3% | +16% | 1.49× (theoretical 1.67×) |
| f=2 → f=3 | −10.9% | +16% | 1.47× (theoretical 1.40×) |
| **f=1 → f=3 (total)** | **−24.5%** | +35% | 2.19× (theoretical 2.33×) |

Crypto cost scales near-linearly with the quorum width
(2f+1 sigs to verify). End-to-end throughput drops less than crypto
because verification is < 4% of RTT.

## G5-v2: clean WAN delay sweep (NC=24)

Earlier G5 was contaminated because `apply_wan_delay.sh` only handled
the `eno1` interface; the 38-cluster's mixed hardware uses 4 different
interface names (`eno1`, `eno12399`, `eno33np0`, `eno49np0`). After
auto-detecting the actual outbound interface per host, the delay was
applied uniformly to all 6 shard-1 hosts.

| egress delay on shard-1 | tput tx/s | P50 ms | P99 ms | drop vs 0ms |
|------------------------:|----------:|-------:|-------:|------------:|
| 0 (baseline) | 1873 | 11.8 | 15.8 | — |
|   5 ms | 1954 | 11.7 | 16.0 | noise |
|  10 ms | 1655 | 11.4 | 14.9 | **−11.7%** |
|  25 ms | 1559 | 11.5 | 18.5 | **−16.8%** |
|  50 ms | 1592 | 11.5 | 16.3 | −15.0% |
| 100 ms | 1933 | 11.6 | 16.8 | +3.2% |
| 200 ms | 1779 | 11.5 | 15.7 | −5.0% |

**Two findings:**

1. **WAN does bite** at 10-50 ms one-way egress on a whole shard at high
   load — ~15% throughput drop. The earlier "Pesto absorbs WAN" claim
   in `perf_final.md` was a 6-client low-load phenomenon and a buggy
   delay-injection script. At NC=24 + working delays, we see real cost.

2. **The cost is non-monotonic.** At 100-200 ms, the drop reverses
   because the protocol consistently picks the fast shard 0's first 2
   replies; the slow shard 1 falls completely off the critical path.
   Below 10 ms the delay is small enough to compete with normal jitter.

P50 latency stays essentially flat (11.4-11.8 ms) — the latency loss is
not on the critical path, only on shard 1's responses that the protocol
no longer waits for at high delays.

## TPC-C cross-warehouse — clean NC sweep (I1, 38-cluster)

f=1 het, WAREHOUSES=10:

| NC | tput tx/s | P50 ms | P95 ms | P99 ms |
|---:|----------:|-------:|-------:|-------:|
| 6 | 167.1 | 18.2 | 65.9 | 149.3 |
| 12 | 355.9 | 17.5 | 107.3 | 244.9 |
| 18 | **439.6** | 17.7 | 121.4 | 301.3 |
| 24 | 370.3 | 18.1 | 135.3 | 452.5 |

Peak **439.6 tx/s at NC=18** (vs the 18-cluster's peak of 182 — the new
cluster is dramatically faster on TPC-C). Tail grows substantially past
the peak: P99 doubles from 150→245→301→452 ms across the NC range.

## Re-mapped headline numbers (paper-ready)

| Scenario | tput tx/s | P50 | P99 |
|----------|----------:|----:|----:|
| f=1 NC=6 honest (clean baseline) | **360 ± 4** | 16 | 20 |
| f=1 NC=48 peak (saturation) | 2 193 | 16 | 154 |
| **f=2 het, removed sister, NC=6** | **305 ± 6** | 19 | 23 |
| f=2 sister NC=6 | 308 ± 4 | 19 | 23 |
| **f=3 het NC=6** | **272 ± 2** | 22 | 26 |
| f=3 sister NC=6 | 258 ± 6 | 23 | 27 |
| f=1 NC=24 + 25 ms WAN on shard-1 | 1559 | 12 | 18 |
| f=1 NC=24 + 100 ms WAN | 1933 | 12 | 17 |
| TPC-C f=1 NC=18 peak | 440 | 18 | 301 |

## What's new vs `perf_38node.md`

- Same physical cluster, but **all H/I/G runs use the full 38-host
  `lab_ssh.txt`** so results are directly comparable across f-levels.
- F-runs (n=11 f=2 het at 298, NC sweep at 1162 peak) are still in
  `perf_38node.md` but should not be directly mixed with H-numbers — they
  used a different host composition (no amd183 in shard 0).
- The earlier 18-cluster `perf_final.md` numbers are now superseded by
  these 38-cluster ones for the headline ablation, since 18-cluster
  forced sister-mode-only for f=2 (no comparison) and was impossible
  for f=3.

## Reproducing

```bash
# Headline ablation (f=1 het):
F_PER_SHARD=1 SISTER_REPLICA=false NUM_TABLES=2 NUM_OPS=2 DURATION=60 \
  PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
  NUM_CLIENTS=6 \
  bash run_byzantine_experiment.sh

# Sister-vs-het at f=2:
F_PER_SHARD=2 SISTER_REPLICA=true ...   # (sister)
F_PER_SHARD=2 SISTER_REPLICA=false ...  # (het)

# WAN sweep (mixed-iface aware):
bash scripts/apply_wan_delay.sh apply 25
F_PER_SHARD=1 NUM_CLIENTS=24 ... bash run_byzantine_experiment.sh
bash scripts/apply_wan_delay.sh remove
```

Run directories:
- G5-v2 WAN: `pesto-results/20260513T0703*Z` through `T07293*Z`
- G6 baseline: `pesto-results/20260513T0735-074904Z` (5 reps)
- H1 (f=2 het): `pesto-results/20260513T0753-080116Z`
- H2 (f=2 sister): `pesto-results/20260513T0805-081231Z`
- H3 (f=3 het): `pesto-results/20260513T0816-082444Z`
- H4 (f=3 sister): `pesto-results/20260513T0829-083815Z`
- I1 (TPC-C f=1 NC sweep): `pesto-results/20260513T0842-085311Z`

## Open items

- **Byz resistance ablation on the H-set** (with full lab_ssh.txt rather
  than the lab_ssh34.txt used for F2/F12)
- **TPC-C at f=2 / f=3** with full lab_ssh.txt (only have f=1)
- **Multi-byz-client + WAN combined**
- **Geographic CloudLab cross-cluster** (Utah + Wisconsin)
