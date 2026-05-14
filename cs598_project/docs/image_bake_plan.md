# Image-Bake Plan — CloudLab Single-Node → 18-Node Pipeline

> CS 598 FTS — Pesto Cross-Shard Extension
> Author / driver: jl180@illinois.edu
> Last edit: 2026-05-09
> **STATUS: Single-node side complete and verified — image is ready for snapshot.**

## Snapshot-readiness checklist (verified 2026-05-09 on hp123.utah.cloudlab.us)

| Item | State | Evidence |
|------|-------|----------|
| `cross-shard-membership` HEAD on node | `ef703550` (SS-CERT wiring) | `git log` |
| Membership unit tests | 34/34 PASS | `membership_test` output |
| Pesto `server` binary | 462 MB, mtime 05:29 (fresh) | `ls -lh` |
| Pesto `benchmark` binary | 326 MB, mtime 05:29 (fresh) | `ls -lh` |
| `sql_tpcc_generator` binary | 8.3 MB | `ls -lh` |
| Server starts past `Notice("Starting Indicus replica")` | yes — proves `membership_cert_loaded` increment didn't crash | smoke test server log line `server.cc:98` |
| TPC-C 10-warehouse data | 657 MB at `/opt/pesto-tpcc-data/` | `du -sh` |
| Elle CLI 0.1.9 jar | `/opt/elle-cli/target/elle-cli-0.1.9-standalone.jar` + symlink `/usr/local/bin/elle-cli.jar` | `java -jar elle-cli.jar` runs |
| Ed25519 keypairs | 129 `.priv/.pub` pairs in `/opt/Pequin-Artifact/src/keys/` | `ls keys/*.priv \| wc -l` |
| Disk usage | 19 GB used / 63 GB total | `df -h /` |
| Test artifacts cleaned | yes | `0_local_test_outputs/{smoke_run,unit_test_logs}` removed |

**What's NOT in v1 (intentionally deferred to v2 after the first 18-node TPC-C run):**

- Client-side `foreign_ss_cert` origination in `querysync-client.cc` —
  needs vote-collection design first. Until this lands,
  `ss_cert_verifications_done` will stay at 0 in production runs even
  with TPC-C cross-shard traffic. The verifier path itself is wired
  and will fire when cert origination is added (one place to enable).
- Reply-side vote attachment — would require extending `SyncReply` proto.

**Local-only changes (don't need to be on the image):**

- `run_byzantine_experiment.sh` now supports `BENCHMARK=tpcc-sql WAREHOUSES=N`
- `run_heterogeneous_experiment.sh` now supports `BYZ_REPLICA_MODE={inconsistency,failure}`
- `scripts/mini_elle.py` now also checks G1a (aborted reads) in addition to G2
- `scripts/install_node_deps.sh` — canonical recipe to recreate this image from scratch on a fresh amd Ubuntu 22.04 node



## Why this doc exists

Each fresh CloudLab launch wipes the disk and gives new IPs. Doing all the
"download / install / compile" work 18 times is wasteful and error-prone.
Instead:

1. Land all code changes locally and push to `cross-shard-membership` branch.
2. Spin up **one** amd node, run the bake script below, snapshot the image.
3. Future 18-node launches start from that image — only SSH key plumbing
   and a quick `git pull` remain.

The plan has four parts, in execution order:

- Part 1 — code changes to push to GitHub before SSH-ing anywhere
- Part 2 — on-node bake commands (run on 1 CloudLab node, then snapshot)
- Part 3 — 18-node experiment sequence after the image is live
- Part 4 — correctness verification per experiment

A scratchpad at the bottom holds open questions and status.

---

# Part 1 — Code changes to land locally first

All edits happen in the local `/home/student/CS598FTS/` working tree. After
each subsection, commit + push to `cross-shard-membership` on
`https://github.com/ljtsparky/Pequin-Artifact.git` so the on-node `git pull`
in Part 2 picks them up.

## 1.1 — Wire SS-CERT into querysync (the dead-code fix)

**Why:** `Server::VerifyForeignSSCert` (`server.cc:2918`) and
`Server::GenerateSnapshotVote` (`server.cc:2911`) compile but are never
called on the hot path. `pesto-results/CROSS_SHARD_FINDING.md` confirms:
0 hot-path call sites in `querysync-server.cc` or `querysync-client.cc`.

**Files to edit:**

| File | Change |
|------|--------|
| `Pequin-Artifact/src/store/pequinstore/server.h` | Add two `std::atomic<uint64_t>` counters: `ss_cert_verifications_done_`, `ss_cert_generations_done_`. Surface in `Stats`. |
| `Pequin-Artifact/src/store/pequinstore/querysync-server.cc` | In `Server::HandleSync` (line 484), after the watermark check (line ~525): if `msg.has_foreign_ss_cert()` then call `VerifyForeignSSCert(msg.foreign_ss_cert())`; if it returns false, drop the message and `Notice("SS-CERT verify FAILED for q=%lu", merged_ss->query_seq_num())`. On success, increment `ss_cert_verifications_done_`. |
| `Pequin-Artifact/src/store/pequinstore/querysync-server.cc` | In the reply path (where `proto::SyncReply` is constructed), call `GenerateSnapshotVote(snapshot_digest, vote)` and attach the vote. Increment `ss_cert_generations_done_`. |
| `Pequin-Artifact/src/store/pequinstore/querysync-client.cc` | When constructing a `SyncClientProposal` for a cross-shard query, set `foreign_ss_cert` to the SnapshotCert collected from the originating shard. (For now: only set when `merged_ss.merged_ts_size() > 0` AND the query touches >1 group — gate behind `params.query_params.crossShardSSCert` flag, default `true`.) |
| `Pequin-Artifact/src/store/pequinstore/server.cc` | In `PrintAndCollectStats` (or equivalent — search for `stats_.Add`), add: `stats_.Add("ss_cert_verifications_done", ss_cert_verifications_done_.load())` and same for generations. |

**Compile & smoke gate:**
```bash
cd Pequin-Artifact/src
make -j$(nproc) store/pequinstore/server.o store/pequinstore/querysync-server.o store/pequinstore/querysync-client.o
make -j$(nproc) store/server/server store/benchmark/benchmark
# Single-shard sanity (counter should stay 0 — no cross-shard txn yet)
./testing/membership_test
```

**Acceptance:** unit tests still pass; binaries compile; counter exists in
stats output (`grep ss_cert_ pesto-results/<run>/stats/client-0.json`
shows the field, value 0 expected on rw-sql workload).

## 1.2 — Add TPC-C support to `run_byzantine_experiment.sh`

**Why:** The existing orchestrator hardcodes `BENCHMARK="rw-sql"`. TPC-C
already exists in `Pequin-Artifact/src/store/benchmark/async/sql/tpcc/`
with the 5 transaction types built; `WarehouseSQLPartitioner` partitions
by warehouse_id at the key level, so cross-shard happens naturally
(~10% of NewOrder line items by spec).

**Files to edit:**

| File | Change |
|------|--------|
| `run_byzantine_experiment.sh` | Branch on `${BENCHMARK}`. When `tpcc-sql`: use `--benchmark=tpcc-sql`, set `--tpcc_num_warehouses=${WAREHOUSES:-10}`, `--data_file_path=/tmp/tpcc/sql-tpcc-tables-schema.json`, drop the rw-sql-only flags (`--num_tables`, `--num_keys`). |
| `run_byzantine_experiment.sh` | Add a pre-load step: if `/tmp/tpcc/loaded` doesn't exist, scp the SQL load files generated by `sql_tpcc_generator` (Part 2 step 2.6) to each server node, then `touch /tmp/tpcc/loaded`. |
| `run_byzantine_experiment.sh` | Document new env vars in header: `BENCHMARK={rw-sql,tpcc-sql}`, `WAREHOUSES=N`, `TPCC_NEW_ORDER_RATIO=45` etc. |

**Acceptance:** running
`BENCHMARK=tpcc-sql WAREHOUSES=4 bash run_byzantine_experiment.sh` on a
single-shard test produces a non-empty stats file with `tpcc_new_order:
NN` counter > 0.

## 1.3 — Add BYZ env vars to `run_heterogeneous_experiment.sh`

**Why:** Exp6 had het OFF + byz OFF; Exp1/2 had het OFF + byz ON. We've
never combined them. This is a one-script-edit and ~30-min run on cluster.

**File:** `run_heterogeneous_experiment.sh`

**Edit:** copy the byz env-var passthrough from `run_byzantine_experiment.sh`:

```bash
BYZ_PER_SHARD="${BYZ_PER_SHARD:-0}"        # 0 = none, 1 = one byz replica per shard
BYZ_REPLICA_MODE="${BYZ_REPLICA_MODE:-inconsistency}"  # inconsistency|failure
BYZ_CLIENT_COUNT="${BYZ_CLIENT_COUNT:-0}"
```

Then plumb the same `--pequin_simulate_inconsistency=true` /
`--pequin_simulate_failure=true` flags into the per-shard server launch
loops, gated by which replica index is chosen as byz (`idx < BYZ_PER_SHARD`).

**Acceptance:** `BYZ_PER_SHARD=1 BYZ_REPLICA_MODE=inconsistency
bash run_heterogeneous_experiment.sh` runs to completion; throughput
within 5% of all-honest het run.

## 1.4 — Extend mini_elle.py with G0 / G1 checks

**Why:** Today `scripts/mini_elle.py` only catches G2 (anti-dep cycles).
Real Elle catches G0 (dirty write), G1a (aborted read), G1b (intermediate
read), G1c (cyclic info flow), G-Single (read skew). Adding G0 and G1a/b
locally is ~80 lines of Python and gives us defense-in-depth before the
real Elle CLI is even installed.

**File:** `scripts/mini_elle.py`

**Edits (sketch):**

```python
def check_g0(ops_by_txn, history):
    """Dirty write: T1 writes x, T2 writes x, T2 commits, T1 aborts.
       Detection: walk WW edges; flag any case where the source txn's
       final status is :fail."""
    ...

def check_g1a_g1b(ops_by_txn, history):
    """G1a: read of an aborted txn's value.
       G1b: read of an intermediate value (not the final committed one).
       Detection: per (key, value), find the txn that wrote it; if that
       txn aborted, any read of that value is G1a; if a later write by
       the same txn changed value before commit, intermediate reads are G1b."""
    ...
```

Wire both into `main()` next to the existing `check_g2_cycles()` call.
Output format unchanged — single PASS / FAIL summary plus per-anomaly
detail.

**Acceptance:** `bash scripts/test_mini_elle.sh` still passes on the
synthetic input; running on the existing `pesto-results/20260505T104108Z/`
honest run still reports PASS.

## 1.5 — (optional, lower priority) Twins client skeleton

Skip in v1 — adds risk without immediate ROI. Defer to next milestone.

---

# Part 2 — On-node bake commands (run on 1 CloudLab node, then snapshot)

After Part 1 commits are pushed, request **one** amd node from the same
profile (or any compatible amd64 Ubuntu image). SSH in. Run the steps
below in order. Each section is copy-pasteable.

## 2.0 — Pre-flight

```bash
# Check we're on the right kind of node
uname -a   # expect Linux ... amd64
nproc      # expect 32+ cores on amd
df -h /    # need 50+ GB free for compile + Intel TBB

# Pick a working dir (NOT /tmp — survives reboot, lives on disk image)
sudo mkdir -p /opt/pesto && sudo chown $USER /opt/pesto
cd /opt/pesto
```

## 2.1 — OS-level dependencies

```bash
# Run Pesto's existing dep installer first (will prompt several times)
git clone https://github.com/ljtsparky/Pequin-Artifact.git
cd Pequin-Artifact
git checkout cross-shard-membership
git pull
bash install_dependencies.sh
# When it pauses for IntelTBB / BFTSmart, hit enter — both auto-resume

# Extras for our verification scripts and Elle integration
sudo apt install -y jq parallel openjdk-11-jre python3-pip
sudo -H pip3 install networkx matplotlib
```

## 2.2 — Download Elle CLI jar

```bash
sudo mkdir -p /opt/elle-cli && cd /opt/elle-cli
wget https://github.com/ligurio/elle-cli/releases/download/0.1.9/elle-cli-bin-0.1.9.zip
unzip elle-cli-bin-0.1.9.zip
# Should produce elle-cli-0.1.9-standalone.jar
ls -lh *.jar
java -jar elle-cli-0.1.9-standalone.jar --help   # smoke check
sudo ln -sf /opt/elle-cli/elle-cli-0.1.9-standalone.jar /usr/local/bin/elle-cli.jar
```

## 2.3 — Build Pesto

```bash
cd /opt/pesto/Pequin-Artifact/src
# Initial full build — takes ~25-30 min on amd
make -j$(nproc)

# Verify the binaries we need
ls -lh store/server/server                                # main BFT server
ls -lh store/benchmark/benchmark                          # benchmark client
ls -lh store/benchmark/async/sql/tpcc/sql_tpcc_generator  # TPC-C data generator
ls -lh store/pequinstore/tests/membership_test            # our membership unit test
```

## 2.4 — Run unit tests (proves SS-CERT changes compile + pass)

```bash
cd /opt/pesto/Pequin-Artifact/src
./store/pequinstore/tests/membership_test
# Expect: PASS for all GenerateCert / VerifyCert / StoreForeignCert tests
```

## 2.5 — Pre-generate TPC-C SQL load files (10 warehouses)

```bash
cd /opt/pesto/Pequin-Artifact/src
sudo mkdir -p /opt/pesto/tpcc-data && sudo chown $USER /opt/pesto/tpcc-data
./store/benchmark/async/sql/tpcc/sql_tpcc_generator \
    --num_warehouses=10 \
    --schema_file=store/benchmark/async/sql/tpcc/sql-tpcc-tables-schema.json \
    --data_dir=/opt/pesto/tpcc-data
# Expect ~50-200 MB of CSV / SQL load files in /opt/pesto/tpcc-data/
ls -lh /opt/pesto/tpcc-data/ | head
du -sh /opt/pesto/tpcc-data/
```

## 2.6 — Single-node smoke test (Pesto end-to-end on loopback)

```bash
cd /opt/pesto/Pequin-Artifact/src
# Generate a 1-shard 6-replica config pointing at 127.0.0.1
mkdir -p /tmp/smoke
cat > /tmp/smoke/shard.config <<EOF
f 1
group
$(for p in 7001 7002 7003 7004 7005 7006; do echo "replica 127.0.0.1:$p"; done)
EOF

# Start 6 servers in background
bash keygen.sh /tmp/smoke 6 1
for i in 0 1 2 3 4 5; do
  ./store/server/server --config_path=/tmp/smoke/shard.config \
    --replica_idx=$i --keys_path=/tmp/smoke/keys \
    > /tmp/smoke/server-$i.log 2>&1 &
done
sleep 3
# Run a 30s rw-sql benchmark with 1 client
./store/benchmark/benchmark --benchmark=rw-sql --num_groups=1 \
  --config_path=/tmp/smoke/shard.config --keys_path=/tmp/smoke/keys \
  --client_id=100 --num_clients=1 --benchmark_duration=30 \
  --data_file_path=/tmp/smoke/rw-sql.json --sql_bench=true \
  > /tmp/smoke/client.log 2>&1
grep -E "commits|aborts|throughput" /tmp/smoke/client.log

# Stop servers
killall server benchmark || true
```

**Acceptance:** client log shows commits > 0, throughput > 5 tx/s. If yes,
the binaries are good; SS-CERT counters will be 0 here (single shard, no
cross-shard traffic) but that's expected.

## 2.7 — Snapshot pre-flight checklist

Before triggering CloudLab "Save as Image":

```bash
# 1. Ensure git is clean
cd /opt/pesto/Pequin-Artifact && git status

# 2. Ensure binaries are present
ls -l src/store/server/server src/store/benchmark/benchmark \
     src/store/benchmark/async/sql/tpcc/sql_tpcc_generator

# 3. Ensure deps are installed (rerun finished message)
ldconfig -p | grep -E "blake3|ed25519|pg_query|protobuf" | head

# 4. Ensure Elle jar is reachable
ls -l /usr/local/bin/elle-cli.jar

# 5. Ensure TPC-C data is pre-generated
du -sh /opt/pesto/tpcc-data/

# 6. Clear any private credentials before snapshot
rm -rf ~/.ssh/id_* /tmp/smoke
history -c
```

Then in the CloudLab portal: Profile → Save as Image. **Tag the image
with the git commit SHA** the build came from (`git rev-parse HEAD` in
`Pequin-Artifact`).

## 2.8 — What lives on the image after snapshot

| Path | Purpose |
|------|---------|
| `/opt/pesto/Pequin-Artifact/` | source + compiled binaries |
| `/opt/pesto/tpcc-data/` | pre-loaded TPC-C SQL data (10 warehouses) |
| `/opt/elle-cli/` | Elle CLI jar |
| `/usr/local/bin/elle-cli.jar` | symlink for convenience |
| `/usr/local/lib/libblake3.so` etc. | crypto deps |

---

# Part 3 — 18-Node Experiment Plan (after image is live)

The order below is the order user wants them run.

## 3.0 — Bring up the 18-node cluster

```bash
# In CloudLab portal: launch the new image as a 18-amd-node profile.
# Wait until all 18 are SSH-able. Update lab_ssh.txt with new hostnames.
cd ~/CS598FTS
# Re-run setup (only SSH key plumbing remains — binaries are baked in)
bash setup_18_nodes.sh
# Sanity: all 18 reachable, all have /opt/pesto/Pequin-Artifact/src/store/server/server
parallel-ssh -h lab_ssh.txt -i 'ls /opt/pesto/Pequin-Artifact/src/store/server/server'
# Pull the latest cross-shard-membership branch on each node
bash scripts/redeploy_18_nodes.sh    # this just does git pull && make -j on each node
```

## Experiment A — TPC-C with cross-shard transactions

**Goal:** prove our SS-CERT verifier path **fires at runtime** under a
real cross-shard workload.

**Config:** 12 servers (6 per shard, 2 shards) + 6 clients.
10 warehouses split across the 2 shards by `WarehouseSQLPartitioner`,
which routes by warehouse_id at the key level. NewOrder includes
~10% remote line items by TPC-C spec → ~10-15% of txns will span shards.

**Command:**

```bash
BENCHMARK=tpcc-sql WAREHOUSES=10 \
BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0 \
bash run_byzantine_experiment.sh
```

**Expected output dir:** `pesto-results/20260MMDDTHHMMSSZ/`

**Acceptance criteria:**

| Metric | Expected | Verify with |
|--------|---------:|-------------|
| `txn_groups[2]+` count > 0 | yes — TPC-C produces cross-shard | `python3 scripts/dsg_check.py pesto-results/<run>` |
| `ss_cert_verifications_done` > 0 | yes — verifier fires on cross-shard receive | `grep ss_cert pesto-results/<run>/stats/server-*.log` |
| `ss_cert_generations_done` > 0 | yes — vote generated on each cross-shard query reply | same |
| Throughput | within 30% of rw-sql baseline (TPC-C is heavier) | `cat AGGREGATE.md` |
| `dsg_check.py` PASS | counters consistent | command above |
| `mini_elle.py` PASS (G0+G1+G2) | no anomalies | `bash scripts/elle_check.sh pesto-results/<run>` |

If `ss_cert_verifications_done` is still 0 after this run, bug is in
Part 1.1 wiring — check `querysync-server.cc HandleSync` for the
`if (msg.has_foreign_ss_cert())` branch.

## Experiment B — Heterogeneous + Byzantine combined (Next-2)

**Goal:** prove per-shard quorum machinery degrades correctly when
heterogeneous shards each take f failures.

**Config:** Shard 0 (n=6, f=1) + Shard 1 (n=11, f=2), 1 byz replica per
shard, omission mode.

**Command:**

```bash
BYZ_PER_SHARD=1 BYZ_REPLICA_MODE=inconsistency \
bash run_heterogeneous_experiment.sh
```

**Acceptance criteria:**

| Metric | Expected |
|--------|---------:|
| Shard 1 still commits with 9-vote quorum (4*f+1 = 9 for f=2) | yes |
| Shard 0 still commits with 5-vote quorum | yes |
| Throughput within 10% of all-honest het run (Exp6 = 408 commits / 30s) | yes |
| `dsg_check.py` PASS | yes |

Then bump to `BYZ_PER_SHARD=2` (saturates Shard 0 at f=1 + sat Shard 1 at
f=2 — wait, no, BYZ_PER_SHARD=2 saturates Shard 1's f=2 but exceeds
Shard 0's f=1 → expect Shard 0 to halt or abort). This is the safety
boundary test — system should refuse to commit on Shard 0 but Shard 1
keeps going.

## Experiment C — Real Elle CLI cross-validation (Next-4)

**Goal:** confirm `mini_elle.py` doesn't miss anomalies that real Elle
catches.

**Command:**

```bash
# Pick the latest TPC-C run from Experiment A
LATEST=$(ls -td pesto-results/2026* | head -1)

# Merge per-client JSONLs into one file (real Elle wants single input)
cat $LATEST/elle/client-*.jsonl > $LATEST/elle/merged.jsonl

# Run real Elle CLI
java -jar /usr/local/bin/elle-cli.jar \
  --model rw-register \
  $LATEST/elle/merged.jsonl > $LATEST/elle/real_elle.txt

# Compare
echo "=== mini_elle ==="
bash scripts/elle_check.sh $LATEST | grep -E "PASS|FAIL|G[012]"
echo "=== real Elle ==="
grep -E "valid|anomaly|G[012]" $LATEST/elle/real_elle.txt
```

**Acceptance:** real Elle's verdict is `:valid? true` or
`:valid? :unknown`. If `:valid? false` and `mini_elle.py` says PASS,
investigate the anomaly real Elle found — it's either a real bug or
a known limitation of our subset.

---

# Part 4 — Correctness Verification Matrix

| Layer | Tool | What it proves | Where the verdict lives |
|-------|------|----------------|-----------------------|
| 1. Protocol invariant | `scripts/dsg_check.py` | counter relationships hold; cross-shard count visible | stdout → `pesto-results/<run>/dsg_check.txt` |
| 2. Data-layer cycles | `scripts/mini_elle.py` (G0+G1+G2) | no dirty write, no aborted/intermediate read, no anti-dep cycle | stdout → `pesto-results/<run>/elle/mini_elle.txt` |
| 3. SS-CERT runtime | counters in stats | verifier+generator actually fired | `grep ss_cert_ pesto-results/<run>/stats/server-*.log` |
| 4. Real Elle (gold) | `elle-cli.jar` | full Adya G0/G1/G1c/G2/G-Single | `pesto-results/<run>/elle/real_elle.txt` |

The combination of Layers 1+2+3+4 gives us:
- Layer 1: no protocol-level state corruption (counters consistent)
- Layer 2+4: no data-level inconsistency (no Adya anomaly)
- Layer 3: our cross-shard heterogeneous-membership code path is
  actually exercised (not just compiled)

A run is "GREEN" if all four layers pass.

---

# Part 5 — Quick reference (after image is baked)

```bash
# Setup (one-time per cluster)
cd ~/CS598FTS
bash setup_18_nodes.sh
bash scripts/redeploy_18_nodes.sh   # git pull on all nodes

# Experiment A: TPC-C cross-shard
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=0 \
  bash run_byzantine_experiment.sh

# Experiment B: heterogeneous + byzantine
BYZ_PER_SHARD=1 BYZ_REPLICA_MODE=inconsistency \
  bash run_heterogeneous_experiment.sh

# Verify any run
LATEST=$(ls -td pesto-results/2026* | head -1)
python3 scripts/dsg_check.py $LATEST
bash scripts/elle_check.sh $LATEST
java -jar /usr/local/bin/elle-cli.jar --model rw-register \
  $LATEST/elle/merged.jsonl
grep ss_cert_ $LATEST/stats/server-*.log
```

---

# Scratchpad — open questions / risks

- **TPC-C ratio defaults**: spec says 45/43/4/4/4 for NewOrder /
  Payment / Delivery / OrderStatus / StockLevel. Pesto's flags exist
  (`--tpcc_new_order_ratio` etc.) but defaults need confirmation —
  re-grep `benchmark.cc:775+` for the `DEFINE_int32` defaults.
- **TPC-C data load**: `sql_tpcc_generator` produces files locally but
  the per-shard servers each need a slice of the data. Need to verify
  how the existing TPC-C path bootstraps tables — likely via the
  initial `--data_file_path` mechanism which loads on first server start.
  If load takes >5 min on cluster, may need to bake the loaded
  PostgreSQL state into the image too.
- **`foreign_ss_cert` originator**: who emits the first SS-CERT? In a
  cross-shard read, the originating shard's replicas must collectively
  sign the snapshot before the client forwards. Need to wire the vote
  collection on the client side in 1.1 (this is the "where does the
  cert come from" gap). MAYBE deferrable to v2 if we just want to
  prove the verify path fires.
- **Image size budget**: CloudLab Utah images cap around 16 GB. Compiled
  Pesto + deps + Elle jar + TPC-C data = estimate 4-6 GB. Should fit,
  but verify with `du -sh /` before snapshot.
- **Membership cert version**: Currently we generate cert with
  version=1 at startup. For Next-6 (live reconfig), version must be
  monotonically updateable. Out of scope here.
