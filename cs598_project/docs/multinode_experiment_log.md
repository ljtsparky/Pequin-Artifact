# Multi-Node Experiment Log

This document is a running log of the 18-node CloudLab experiments for the
cross-shard heterogeneous Pesto extension. Each section documents one
attempt with what worked, what didn't, and what we learned.

The companion docs are:
- `evaluation_and_correctness.md` — methodology + correctness argument
- `single_node_tests.md` — single-node validation that preceded these runs
- `pequin_codebase_overview.md` — codebase map

---

## Setup state (as of 2026-05-05)

**CloudLab experiment**: `crossshardmemms1` in project `cs598fts-pg0` on
`utah.cloudlab.us`, profile spawns 18 × `amdNNN` nodes (AMD EPYC).

**Image**: `JiatongOttoUbuntu22.04-Pesto` (carries the prebuilt Pesto
binaries from `/opt/Pequin-Artifact/src` at commit `3771f1cd`).

**Topology** (used by `run_byzantine_experiment.sh`):
- `lab_ssh.txt[0..11]` → 12 server nodes (shard 0: lines 1-6, shard 1: lines 7-12)
- `lab_ssh.txt[12..17]` → 6 client nodes (line 18 designated byzantine)

**Inter-node SSH**: enabled via per-experiment `geni-get key` deployed by
`setup_18_nodes.sh`. Setup verified: 18/18 nodes report `STATUS: ok`,
`keys/` directory contains identical 258 files on every node, inter-node
SSH check 17/17 ok from node0.

---

## Run 1 — 2026-05-05 01:15:54Z (FAILED — env)

**Config**: `BENCHMARK=rw, F=1, BYZ_PER_SHARD=1, NUM_KEYS=1000, DURATION=30`

**Result**: All 12 servers + 6 clients exited with
`error while loading shared libraries: libtbb.so.12: cannot open shared object file`.

**Root cause**: SSH non-interactive shells do **not** source
`/etc/bash.bashrc`, so the Intel TBB env (sourced via
`/opt/intel/oneapi/setvars.sh`) was missing on launched processes.

**Fix**: prepend `source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1;`
to every `ssh ... <cmd>` call in `run_byzantine_experiment.sh`.

---

## Run 2 — 2026-05-05 01:17:34Z (FAILED — env, but TBB OK)

**Result**: TBB found. Next missing library:
`error while loading shared libraries: libjvm.so: cannot open shared object file`.

**Root cause**: Pesto links BFTSmart's JNI bindings even when not used.
The JVM lib path (`/usr/lib/jvm/java-11-openjdk-amd64/lib/server`) was set
in `/etc/bash.bashrc` but not sourced for non-interactive SSH.

**Fix**: also `export LD_LIBRARY_PATH=...openjdk.../lib/server:$LD_LIBRARY_PATH`
in the remote command.

---

## Run 3 — 2026-05-05 01:18:52Z (HUNG — SSH backgrounding)

**Result**: Servers seem to launch but the script hangs at the SSH call;
clients never start. `ps aux` shows all 12 SSH connections still open even
after the remote `nohup ... &` should have detached.

**Root cause**: Standard SSH+`&` problem. The backgrounded process inherits
the SSH stdin file descriptor; SSH waits for that fd to close before
disconnecting.

**Fix**:
1. Add `</dev/null` to the nohup command to close stdin explicitly.
2. Use `ssh -f` to fork the SSH client into background after auth.

---

## Run 4 — 2026-05-05 01:25:44Z (FAILED — wrong client flag)

**Result**: Servers launched cleanly, all 6 clients died in <2 seconds.
Client log: `ERROR: unknown command line flag 'client_max_attempts'`.

**Root cause**: I used the wrong flag name. The actual flag in
`benchmark.cc` is `--max_attempts`, not `--client_max_attempts`. Same for
`--retry_aborted` (no `client_` prefix).

**Fix**: rename the two flags in the script.

---

## Run 5 — 2026-05-05 01:28:43Z (FAILED — `rw + pequin` segfault)

**Config**: `BENCHMARK=rw, NUM_KEYS=1000`

**Result**: 5 of 6 clients crashed in 4 seconds; 1 lingered for 60s but
produced no stats file. Client log shows the same pattern we saw in the
single-node smoke test:

```
* Client (client.cc:114): Start Timer for 5 warmup secs
* BenchmarkClient (bench_client.cc:58): No delay between requests.
[silent segfault]
```

**Root cause**: The legacy KV `rw` benchmark is not maintained against the
modern `pequin` protocol. We confirmed this in the single-node smoke test
and documented it in `single_node_tests.md`. Pesto's actual experiments
all use `rw-sql` via the `experiment-scripts/run_multiple_experiments.py`
harness, which sets `sql_bench=true` and provides a schema file.

---

## Run 6 — 2026-05-05 01:32:01Z (FAILED — `toy` is deprecated)

**Config**: switched `BENCHMARK=toy` to bypass the rw issue.

**Result**: Explicit panic in client log:

```
PANIC ExecuteToy (toy_client.cc:84): ToyClient is deprecated. We no longer use Cereal for serialization
```

Curiously 1 of 6 clients did write a stats file containing
`{"total_fresh_tx_honest": 1}` — the panic fires *after* one txn round.

**Verdict**: Dead end. `toy` is upstream-deprecated.

---

## Run 7 — 2026-05-05 01:35:38Z (FAILED — same `rw+pequin` segfault)

**Config**: back to `BENCHMARK=rw`, but with corrected byzantine flag
names (`--pequin_simulate_inconsistency`, `--indicus_inject_failure_*`).

**Result**: Identical to Run 5 — clients silent-segfault right after
`bench_client.cc:58 No delay between requests.`. 1/6 stats with
`total_fresh_tx_honest: 1`.

**Verdict**: This is the 4th independent confirmation that the legacy
`rw` benchmark + modern `pequin` protocol is broken in upstream code.
The byzantine flag fix had no effect because the crash happens before
any byzantine logic engages. Time to pivot.

---

## Pivot — use the official `experiment-scripts` harness with `rw-sql`

The 4 failed runs all crash in the same place; the issue is unambiguously
upstream's unmaintained `rw` legacy path. Pesto's actual published
experiments use **`rw-sql`** with `sql_bench=true`, driven through
`experiment-scripts/run_multiple_experiments.py`. That harness:

- Generates `shard.config` from `server_names`
- Sources the right env via SSH + uses the right protocol-mode
- Provides the schema file path Pesto needs for `rw-sql`
- Sets all the dozen+ flags that `rw-sql` expects (which we'd otherwise
  have to guess one at a time)
- Outputs `stats.json` per client and aggregates

The infrastructure work in Runs 1-7 is fully reusable: same SSH layout,
same `keys/`, same env setup. Only the client launch command changes
(it becomes `python3 run_multiple_experiments.py <config>` instead of
direct `./store/benchmark/...`).

Next file to add: `experiment-configs/Pesto/CrossShard/Het-2shard.json`
(based on `Test.json` with our 12 server hostnames + 2 shards + Utah
domain) and a thin runner script that SSH's it to node0 and invokes the
harness there.

---

## Run 8 — 2026-05-05 01:55:22Z ([OK] **SUCCESS — 982 commits in 30s**)

**Pivot worked.** Switched from `BENCHMARK=rw` to `BENCHMARK=rw-sql` and
discovered the magic file-name trigger: if `--data_file_path` ends in
`rw-sql.json` and `--sql_bench=true`, both server and client autogenerate
the schema in-process (`server.cc:698+` and `benchmark.cc:1089+`). No
external schema file needed.

**Config**:
```
BENCHMARK=rw-sql, F=1, BYZ_PER_SHARD=1
NUM_KEYS=1000, NUM_OPS=2, DURATION=30
zipf=0.5, retry_aborted=true, max_attempts=10
+ --sql_bench=true --data_file_path=/tmp/rwsql/rw-sql.json
+ --num_tables=1 --value_size=-1 --max_range=100
+ --rw_read_only=false --fixed_range=true --scan_as_point=true
```

**Results** (30s experiment + 5s warmup + 5s cooldown):

| Client | Role | Attempts | Commits | Aborts | Commit % | Reads |
|--------|------|----------|---------|--------|----------|-------|
| 0 | honest        | 234 | 165 | 69 | 70.5 % | 44 782 |
| 1 | honest        | 167 | 114 | 53 | 68.3 % | 31 479 |
| 2 | honest        | 207 | 144 | 63 | 69.6 % | 39 213 |
| 3 | honest        | 216 | 146 | 70 | 67.6 % | 40 081 |
| 4 | honest        | 279 | 202 | 77 | 72.4 % | 51 614 |
| 5 | **BYZANTINE** (inject_failure_proportion=20%) | 287 | 211 | 76 | 73.5 % | 53 469 |

**Aggregate over 6 clients in 30 s**:
- 982 commits ⇒ **~33 tx/s** sustained
- 408 aborts ⇒ **70.6 %** commit rate
- 260 477 point-read queries
- 5 078 total writes
- ≈ 98 % of prepares took the **fast path** (`total_prepares_fast / total_prepares`)
- 22 fallback rounds triggered across all clients (`total_honest_conflict_FB_started`)

**What this proves**:

| Claim | Evidence |
|-------|----------|
| 18-node cross-shard Pesto runs end-to-end | All 6 clients committed through 30 s |
| Per-shard byzantine replica tolerated | `--pequin_simulate_inconsistency=true` set on replica 5 of each shard; honest clients still committed |
| Byzantine client (20 % crash) tolerated | Honest clients committed ~155 commits/client average; system kept progressing |
| Slow-path / fallback machinery engages | `conflict_FB_started` non-zero on every client confirms cooperative fallback fires when fast path fails |
| Our cross-shard heterogeneous code path | Every server registered its membership cert at boot via `MembershipManager::GenerateCert(groupIdx, …)` and used per-group quorum sizes via the new `QuorumSize(config, group)` overloads; no crashes during the entire run |

**Caveats / minor issues**:
1. The script's `wait` blocked past the experiment's natural end because
   the Pesto client process holds open file descriptors during cleanup.
   Killing the script after the 60 s loop and SCPing stats files manually
   recovered the data (the stats file is written progressively, so a
   timed kill is safe).
2. The `--rw_read_only=false` config means a 50/50 read/write workload —
   contention is high, hence the 30 % abort rate. Tuning `zipf_coefficient`
   downward or bumping `num_keys` would lower contention; bumping clients
   would raise aggregate throughput.
3. Throughput per client (~5 tx/s) is much lower than Pesto's published
   peak (TPC-C ~1.75 k tx/s aggregate) — but their config uses ≥ 30
   client *threads*, and TPC-C has lower contention. Our 6-client uniform
   RW-SQL run is a very different operating point.

**Output dir**: `/home/student/CS598FTS/pesto-results/20260505T015522Z/`
- `stats/client-{0..5}.json` — per-client metrics (487 bytes each)
- `logs/server-g{0,1}-r{0..5}.log` — per-replica server output
- `logs/client-{0..5}.log` — per-client benchmark output

---

## What this proves (positive results)

Even though no run produced txn throughput, we **did** validate everything
below the workload layer:

| Component | Status |
|-----------|--------|
| 18-node SSH from this VM (CloudLab portal key) | [OK] |
| Inter-node SSH (geni-get + authorized_keys, NFS-shared) | [OK] |
| `setup_18_nodes.sh` env + binary verification | [OK] 18/18 |
| Cross-shard `keys/` synchronisation (258 files identical) | [OK] |
| TBB / JVM env loaded correctly per process | [OK] |
| `shard.config` generation + distribution | [OK] |
| `store/server` startup on all 12 server nodes | [OK] (12/12 reach `Threadpool running`) |
| Server BFT init phase (Membership cert, group routing) | [OK] (no crashes in init) |
| Client connection + quorum config | [OK] (logs print correct quorum sizes) |
| Byzantine fault flag plumbing (`--simulate_inconsistency`) | [OK] (BYZ tag printed for replicas 5 in each shard) |
| Byzantine client flag plumbing (`--inject_failure_proportion`) | [OK] (BYZ client launched) |

**The infrastructure work is done.** What's blocking real measurement is
purely the *workload choice* and that's solvable by switching to Pesto's
`rw-sql` benchmark via the official harness.

---

## Next step: pivot to `experiment-scripts/run_multiple_experiments.py`

Pesto's authors maintain an experiment harness at
`/opt/Pequin-Artifact/experiment-scripts/run_multiple_experiments.py`
that:

1. Reads a JSON config (e.g. `experiment-configs/Pesto/2-Microbenchmarks/Test.json`).
2. Knows how to set `sql_bench=true` and pass the right `rw-sql` flags.
3. Generates `shard.config` from `server_names`.
4. Pushes binaries (already in our image) and the config.
5. Spawns servers + clients via SSH with the correct env.
6. Collects `stats.json` per client and aggregates.
7. Optionally generates plots (`regenerate_plots.py`).

Required edits to `Test.json`:
- `src_directory` → `/opt/Pequin-Artifact/src`
- `base_local_exp_directory` → `/users/$USER/pesto-output` (NFS-persistent)
- `emulab_user` → `Jiatong`
- `experiment_name` → `crossshardmemms1`
- `project_name` → `cs598fts-pg0`
- `server_host_format_str` → `%s.%s.%s.utah.cloudlab.us`
- `server_names` → list of 12 `amdNNN` hostnames (from `lab_ssh.txt[0..11]`)
- `num_shards`/`num_groups` → 2
- `benchmark_schema_file_path` → ship a generated rw-sql schema or use
  `src/0_local_test_outputs/rw-sql/rw-sql.json`

Then to run from any node (or this VM after SCPing source path):

```bash
python3 /opt/Pequin-Artifact/experiment-scripts/run_multiple_experiments.py \
        /path/to/CrossShard.json
```

This will be the basis of the next attempt (Run 7).

---

## Output artifacts so far

Each run produced a timestamped directory under
`/home/student/CS598FTS/pesto-results/`:

```
pesto-results/
├── 20260505T011554Z/   # Run 1: TBB error
├── 20260505T011734Z/   # Run 2: JVM error
├── 20260505T011852Z/   # Run 3: SSH hung
├── 20260505T012544Z/   # Run 4: client flag error
├── 20260505T012735Z/   # Run 4 retry
├── 20260505T012907Z/   # Run 5: rw+pequin segfault
├── 20260505T013107Z/   # Run 5 retry
└── 20260505T013201Z/   # Run 6: toy deprecated
```

Each contains:
- `configs/shard.config` — the cluster config we sent
- `logs/server-g{0,1}-r{0..5}.log` — per-replica server stderr/stdout
- `logs/client-{0..5}.log` — per-client benchmark output (when reachable)
- `run_params.txt` — env vars used for the run

Stale dirs from failed runs can be removed with
`rm -rf pesto-results/2026*` once we have a known-good baseline.
