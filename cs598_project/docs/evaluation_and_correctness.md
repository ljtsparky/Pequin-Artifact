# Evaluation Methodology and Correctness Argument

This document specifies how we will validate our cross-shard heterogeneous
membership extension to Pesto. It is organized into two halves:

- **Part I -- Correctness**: how we establish that our protocol still upholds
  Byz-serializability and Byzantine independence after removing the sister
  replica assumption.
- **Part II -- Performance Evaluation**: what we measure, against what
  baselines, and on what workloads.

The methodology mirrors and extends the evaluation strategies in the Pesto
SOSP'25 paper (§7, §A) and the Basil SOSP'21 paper (§6, technical report).

---

## Part I -- Correctness

### 1. What "correctness" means here

We adopt Basil's two formal properties (Basil §2.2), which Pesto inherits:

1. **Byz-serializability** (safety): every correct client sees a sequence of
   states consistent with a serial execution of concurrent transactions, even
   when up to *f* replicas per shard and an unbounded number of clients are
   Byzantine.
2. **Byzantine independence** (Basil §2.2; Pesto §A.4): no group of solely
   Byzantine actors can unilaterally dictate the result of an operation
   issued by a correct client.

Pesto formalizes the safety argument as a direct serialization graph (DSG)
proof (Pesto Lemma 1, §A.2): for every conflict edge `T_i --rw|wr|ww--> T_j`,
the timestamps satisfy `ts_out < ts_in`, so the DSG is acyclic and the
execution serializable.

**Our project's correctness obligation**: removing the sister-replica
assumption must not break either property. Specifically:

- (a) Cross-shard SS-CERTs must be **unforgeable** by a Byzantine client.
- (b) `T_global` computation must produce a value **observable by some
  correct replica** of every involved shard, otherwise reads will see
  inconsistent snapshots.
- (c) Nested-query result `R` must be **cryptographically bound** to
  `SS-CERT_i`, so a Byzantine client cannot substitute a fabricated `R'`
  to redirect the outer query to attacker-chosen shards.
- (d) Per-group quorum thresholds must be applied **per shard**, not
  globally, so that a shard with `f_g = 2` is not certified by `2*1+1 = 3`
  votes when `2*f_g+1 = 5` are needed.

### 2. Correctness argument (sketch)

#### 2.1 Membership Certificate is unforgeable

Each `ShardMembershipCert` carries a `cert_digest = BLAKE3(group_id ||
version || f || n || replica_ids...)`. Because BLAKE3 is collision-resistant,
any tampering with the listed replicas, fault threshold, or version produces
a different digest -- detected by `MembershipManager::VerifyCert`.

The version number is monotonic (`StoreForeignCert` rejects older or equal
versions), so a Byzantine actor cannot replay a stale certificate to
authenticate signatures from a replica that has been removed.

> **Trust root**: in this prototype, `cert_digest` integrity protects the
> *contents*. In production the digest would be co-signed by the shard's
> administrator(s) so foreign shards can verify the **origin** as well; we
> document this below as future work.

#### 2.2 SnapshotCert is unforgeable without f+1 correct compromises

`VerifySnapshotCert` (`common.cc`) checks:

1. `cert.group_id == membership_cert.group_id`.
2. `cert.membership_version == membership_cert.version` (no stale members).
3. `votes_size >= 2f+1` from **distinct** replicas.
4. Every voter is listed in the membership cert.
5. Every Ed25519 signature verifies against the listed public key over
   `snapshot_digest [|| result_hash]`.

Because correct replicas only sign snapshot digests they actually computed,
forging a `SnapshotCert` requires either:

- compromising ≥ f+1 correct replicas (impossible by the BFT assumption), or
- a digital signature forgery on Ed25519 (cryptographically infeasible).

A Byzantine *client* can collect votes for snapshots that were proposed but
never committed; this is **not** a forgery, just a stale snapshot. Stale
snapshots are detected at the receiving shard during CC-check (Pesto Lemma
6), which aborts the resulting transaction.

#### 2.3 `T_global` is observable by every involved shard

For each shard `g`, the client requests `committed_frontier` from `3*f_g+1`
replicas, sorts the values, and takes the `(f_g+1)`-th smallest as the
shard's frontier. Then `T_global = min` across shards.

**Why the (f+1)-th smallest is correct**: of the `3f+1` replies, at most
`f` may originate from Byzantine replicas. Byzantine replicas can freely
*inflate* their reported frontier (which only forces the system to do
extra historical reads) but cannot *deflate* it without contradicting their
own shard's snapshot history. So the `(f+1)`-th smallest value is
guaranteed to come from a correct replica, and is no greater than that
correct replica's actual committed frontier.

**Why `min` across shards is correct**: each per-shard frontier is at least
as low as some correct replica's committed state, so `T_global` is
observable by at least one correct replica of every involved shard. Pesto
uses MVCC (§B.3), so each correct replica can reconstruct its state at
`T_global` even if it has since received fresher writes.

#### 2.4 Nested queries: hash binding prevents result substitution

The two-phase nested protocol works as follows:

- **Phase 1**: client executes inner query `Q_i` at `T_global`; collects
  result `R` and `SS-CERT_i` whose votes sign `BLAKE3(snapshot_digest ||
  H(R))` where `H(R)` is the BLAKE3 hash of `R` computed by inner-shard
  replicas.
- **Phase 2**: client sends `R` plus `SS-CERT_i` to outer-shard replicas
  along with `Q_o`. Each outer replica recomputes `H(R)` from the received
  bytes and verifies it matches the hash embedded in the SS-CERT signatures.

A Byzantine client trying to substitute `R'` would need to either:

- forge ≥ f+1 inner replicas' signatures over `H(R')` (cryptographically
  infeasible), or
- find `R' != R` such that `H(R') == H(R)` (BLAKE3 collision; infeasible).

Therefore, the outer query's data-access pattern is **fully determined** by
the verified inner result, preserving the Byz-serializability invariant
that all sub-queries execute against the same logical snapshot at
`T_global`.

#### 2.5 Per-group quorum sizes preserve Pesto's CC-check guarantees

Pesto Lemma 6 (CC-check detects stale ARS) and Lemma 7 (CC-check detects
incomplete ARS) rely on quorum intersection. Specifically, Pesto requires
at least `3f+1` replicas to vote commit (`SlowCommitQuorumSize`), so that
any two such quorums intersect in at least `f+1` correct replicas.

In the heterogeneous setting, both quorums are taken **inside the same
shard** (the cross-shard 2PC step combines per-shard quorums), so the
intersection argument is per-shard. Our `SlowCommitQuorumSize(config, g)
= 3*f_g+1` preserves this property as long as `n_g = 5*f_g+1`.

The `IsReplicaInGroupHeterogeneous` check uses cumulative ID offsets
rather than host matching, so it correctly identifies which replicas
belong to which shard regardless of physical hosting.

### 3. Correctness verification plan (executable)

#### 3.1 Unit tests (already implemented)

`src/store/pequinstore/tests/membership_test` -- 34 assertions, all
passing. Coverage:

- Per-group `n` and `f` accessors return the right values.
- `GlobalReplicaId` and `GroupAndIdx` are exact inverses for every replica
  in a heterogeneous configuration.
- Per-group quorum sizes (`QuorumSize`, `SlowCommitQuorumSize`,
  `SlowAbortQuorumSize`, `FastQuorumSize`) compute correctly for groups
  with different `n`/`f`.
- `IsReplicaInGroupHeterogeneous` correctly classifies global IDs into
  their shards and rejects cross-shard IDs.
- Membership cert tampering is detected by `VerifyCert`.
- `MembershipManager` enforces monotonic version numbers (rejects stale,
  accepts newer).

Run with `./store/pequinstore/tests/membership_test`.

#### 3.2 Integration tests (planned)

| Test | What it checks | How |
|------|----------------|-----|
| **T1: Homogeneous regression** | No regression on existing benchmarks | Run `experiment-configs/Pesto/2-Microbenchmarks/Test.json` unmodified. Output should match `sample-output/`. |
| **T2: Heterogeneous 2-shard** | New code path works at all | Two shards, disjoint hosts, both with `f=1`. Use existing `rw-sql` workload but partition keys across shards. |
| **T3: Cross-shard SS-CERT exchange** | Foreign SS-CERTs verify correctly | T2 with cross-shard transactions enabled. Instrument `VerifyForeignSSCert` to count successful verifications. |
| **T4: Tampered SS-CERT rejected** | Bad votes are rejected | Inject a fake `SnapshotVote` with random signature; verify `VerifySnapshotCert` returns false. |
| **T5: Mismatched membership version rejected** | Version mismatch is detected | Send an SS-CERT referencing version 2 when only version 1 cert is published; verify rejection. |
| **T6: Per-shard `f` heterogeneity** | Shards with different `f` co-exist | Shard 0 with `f=1`, Shard 1 with `f=2`; cross-shard txn commits and reads correctly. |

#### 3.3 Byzantine fault injection

Pesto already has fault-injection hooks in the codebase:

- **`simulate_replica_failure`** flag (`server.cc`): a replica configured
  with this flag drops messages or stops responding -- crash failures.
- **`simulate_inconsistency`** flag: simulates Byzantine inconsistency by
  omitting/delaying writes of a fraction of replicas (Pesto §7.3).
- **`simulate_point_kv`** flag: alternative consistency simulation.

We will use these for:

- **F1: f crash failures per shard, heterogeneous**: T2 with `f=1`
  failures on each shard. Expect commits to succeed via slow-path quorums.
- **F2: Byzantine inconsistency under heterogeneity**: T2 with
  `simulate_inconsistency` on one replica per shard. Expect the SS-CERT
  exchange to still succeed because `2f+1` correct replicas remain.
- **F3: Stalling Byzantine client across shards**: client begins a
  cross-shard transaction, receives Phase1 from one shard, then stalls.
  Expect Basil's cooperative fallback (still inherited by Pesto) to
  recover.

#### 3.4 Offline serialization-graph check (Elle-style)

This is the strongest correctness argument: build the DSG from a
production trace and verify it is acyclic.

1. **Instrumentation**: in `server.cc`, on each commit, append to a log
   file: `(client_id, txn_id, ts, read_set, write_set, dependencies)`.
2. **Aggregation**: collect logs from all replicas of all shards.
3. **DSG construction** (Python script):
   - For each pair of committed transactions `(T_i, T_j)`, add an edge
     `T_i -ww-> T_j` if both write the same key and `ts_i < ts_j`.
   - Add `T_i -wr-> T_j` if `T_j` reads a value `T_i` wrote.
   - Add `T_i -rw-> T_j` if `T_i` reads a value, then `T_j` writes a
     newer version of the same key with `ts_i < ts_j`.
4. **Acyclicity check**: run Tarjan's SCC algorithm; expect no SCC of
   size > 1.

The Elle paper (Kingsbury & Alvaro, VLDB'20, downloaded as
`elle_arxiv.pdf`) describes this technique formally and is the basis of
Jepsen's Elle checker. We will reuse the same edge-construction rules,
adapted to per-row MVCC versions instead of list-append registers.

> **Why this is necessary even with unit tests**: unit tests verify the
> *cryptographic* layer. The DSG check verifies the *protocol* layer --
> that the cryptographic guarantees actually translate into serializable
> executions. Pesto's own proofs (§A.2) reason about exactly this DSG.

#### 3.5 Twins-style adversarial scenario generator (stretch goal)

Twins (Bano et al., OPODIS'21, downloaded as `twins_opodis21.pdf`) is the
standard tool for systematic Byzantine attack scenario generation. It
runs two copies of a node with the same identity -- the "twins" -- to
emulate equivocation, double voting, and lock-forgetting attacks.

Twins is implemented for DiemBFT and HotStuff. Adapting it to Pesto is
significant engineering, but the *idea* is directly applicable: for each
of our new code paths (frontier reporting, SS-CERT generation, foreign
SS-CERT verification), enumerate the small set of "lies" a Byzantine
replica could tell and verify the protocol still tolerates `f` such
lies.

For this project, we apply the Twins idea informally:

- For each new message handler, list the worst-case Byzantine deviations.
- Confirm that `2f+1`-of-`5f+1` quorum intersection still includes
  `f+1` honest votes.
- Document the deviation in the per-shard correctness argument above.

### 4. What we are NOT verifying

To keep the scope tractable:

- **Liveness under partial synchrony**: Pesto itself does not implement
  exponential backoff for view changes (per the README), and neither do
  we. We assume best-effort progress.
- **Network partitions**: outside the BFT model in both papers.
- **Membership reconfiguration at runtime**: we assume static membership
  with version 1; reconfiguration would require a separate consensus
  protocol on the cert version.
- **DoS resistance**: the original Basil paper notes that BFT systems
  cannot prevent DoS by message flooding (§2.1).

---

## Part II -- Performance Evaluation

### 5. Evaluation questions

Mirroring Pesto §7, we ask:

- **Q1**: How much performance overhead does our cryptographic SS-CERT
  exchange add over the sister-replica shortcut? (cost of the new
  protocol)
- **Q2**: What throughput and latency does Pesto achieve when shards
  have completely independent membership? (target deployment)
- **Q3**: How does the system degrade under `f` Byzantine faults per
  shard in the heterogeneous setting? (resilience)
- **Q4**: How does the cross-shard transaction fraction affect
  throughput? (workload scaling)

### 6. Experimental setup

#### 6.1 Hardware

We will follow Pesto's setup as closely as our resources allow:

- **Pesto's spec** (§7): CloudLab `m510` machines (8-core 2.0 GHz, 64 GB
  RAM, 10 GB NIC, 0.15 ms ping latency).
- **Our local setup**: single multi-core machine, simulating shards on
  separate processes / loopback.
- **CloudLab option**: if available, we will use `m510` to enable direct
  comparison with Pesto's published numbers.

#### 6.2 Baselines (three configurations)

| Configuration | Description | Isolates |
|---------------|-------------|----------|
| **Pesto-Original** | Unmodified Pesto from `main` branch, sister-replica assumption intact | Reference |
| **Pesto-Homogeneous** | Our protocol, but all shards share the same authority set (same physical hosts) | Pure crypto overhead of our additions |
| **Pesto-Heterogeneous** | Our protocol with disjoint authority sets across shards | Target deployment cost |
| **Pesto-Heterogeneous-Fault** | Heterogeneous + `f=1` Byzantine replica per shard via `simulate_replica_failure` and `simulate_inconsistency` | Resilience under attack |

The first two share the same physical deployment and differ only in
which code paths run -- the difference quantifies our overhead.

#### 6.3 Workloads

We use the same microbenchmarks Pesto used (§7.3, §7.4):

- **YCSB-Tables (uniform)**: 10 tables × 1M keys, 10-row read-modify-write
  transactions, uniform key distribution.
- **YCSB-Tables (Zipfian)**: same with Zipf coefficient 1.1 (heavily
  contended).
- **Cross-shard fraction sweep**: 0%, 25%, 50%, 100% of transactions
  span multiple shards. (This isolates the cost of our cross-shard
  protocol.)

We can reuse Pesto's existing config files in
`experiment-configs/Pesto/2-Microbenchmarks/` with two modifications:

1. Set `num_shards = 2` (or 4) and provide a partitioner config.
2. Add new heterogeneous configs that specify `group_f` per shard
   (the new directive we added to `configuration.cc`).

For full SQL workloads (TPC-C, AuctionMark, SEATS), the existing configs
in `1-Workloads/` apply once we run with multiple shards. Pesto §7.2
Figure 6 already shows scalability across 1–3 shards for TPC-C.

### 7. Metrics

We measure the same metrics as Pesto §7:

| Metric | How collected | Pesto's reported numbers (for comparison) |
|--------|--------------|--------------------------------------------|
| **Throughput** (tx/s) | Each client thread reports completed txns / wall clock; sum over clients | TPC-C: 1784 tx/s; AuctionMark: ~3000; SEATS: ~6000 |
| **End-to-end latency** (ms) | Time from `BEGIN` to commit-callback | TPC-C: ~30 ms median |
| **Crypto overhead** (µs) | `Latency_Init` instrumentation around `crypto::Sign` and `VerifySnapshotCert` | New metric |
| **Extra messages** | Counter on `FrontierRequest`, SS-CERT-bearing messages | New metric |
| **Failure-mode degradation** | Throughput at peak with `f` faults vs no faults | Pesto §7.4 Figure 9 |

The codebase already has the `Stats` infrastructure (`store/common/stats.h`)
for collecting these. We add new stat keys:
- `ss_cert_gen_us`, `ss_cert_verify_us`
- `membership_cert_verify_us`
- `cross_shard_messages_sent`, `cross_shard_messages_recv`

### 8. Experiment matrix

| Experiment | Workload | Shards | Configurations | What it answers |
|-----------|----------|--------|----------------|-----------------|
| **E1** | YCSB-U | 1 | All four | Single-shard regression |
| **E2** | YCSB-U | 2 | All four | Q1, Q2: cross-shard cost |
| **E3** | YCSB-U, varying cross-shard % | 2 | Heterogeneous | Q4: workload scaling |
| **E4** | YCSB-Z (Zipfian) | 2 | All four | Contention behavior |
| **E5** | YCSB-U with `f=1` faults | 2 | Heterogeneous-Fault | Q3: resilience |
| **E6** | TPC-C | 2, 3 | Heterogeneous | SQL workload, sharding |

Each run: 60 s with 15 s warmup and 15 s cooldown (matching Pesto §7).

### 9. Plotting & reporting

We will reuse `experiment-scripts/regenerate_plots.py` (already in the
codebase) for generating throughput-vs-latency curves like Pesto's
Figures 3-5. The four configurations get distinct line styles; cross-
shard fraction is plotted as separate panels.

---

## Part III -- Existing BFT testing tools we surveyed

For completeness, here are the standard BFT testing tools we considered
or will use:

| Tool | What it does | Use here |
|------|-------------|----------|
| **Pesto's own benchmarks** (`experiment-scripts/`, `experiment-configs/`) | Drives multi-machine experiments, parses logs, runs YCSB / TPC-C / AuctionMark / SEATS | **Primary**: directly applicable, just need new heterogeneous configs |
| **Pesto's `simulate_replica_failure`, `simulate_inconsistency` flags** | In-source fault injection at the replica level | **Primary**: our F1, F2 tests use these |
| **Twins** (Bano et al., OPODIS'21; in DiemBFT) | Systematic Byzantine attack scenario generation via "twin" nodes that emulate equivocation, double voting, lock loss | **Stretch goal**: ideas applied informally; full integration is a separate engineering effort. PDF at `twins_opodis21.pdf`. |
| **Jepsen + Elle** (Kingsbury & Alvaro, VLDB'20) | External black-box safety checker; constructs DSG from observed reads/writes and detects cycles | **Adopted**: our offline DSG check (§3.4) follows Elle's edge-construction rules. PDF at `elle_arxiv.pdf`. |
| **ByzzFuzz** (Gleissenthall et al.) | Randomized testing of BFT algorithms | Future work |
| **Maelstrom** (jepsen-io/maelstrom) | Workbench for toy distributed system implementations + Byzantine Paxos checking | Not applicable: aimed at toy implementations, not production C++ codebases |
| **BFTDiagnosis** | Automated security testing with malicious behavior injection | Future work |

The papers we downloaded for this section:

- `pesto_sosp25.pdf` -- Pesto SOSP'25, our base system
- `basil_sosp21.pdf` -- Basil SOSP'21, the predecessor
- `twins_opodis21.pdf` -- Twins, BFT scenario generator
- `elle_arxiv.pdf` -- Elle, the DSG-based serializability checker

---

## Part IV -- What "done" looks like

We will consider the project successfully evaluated when:

- [x] All 34 unit tests pass (membership cert, quorums, ID mapping).
- [ ] T1 homogeneous regression matches the original Pesto sample output
  within ±5%.
- [ ] T2-T6 integration tests pass on a 2-shard heterogeneous setup.
- [ ] F1-F3 fault tests show no safety violations and tolerable
  throughput degradation (Pesto's reference: 14-36% drop, §7.4).
- [ ] Offline DSG check (§3.4) on a 60-second trace produces an acyclic
  graph.
- [ ] Performance experiment E2 quantifies the SS-CERT overhead vs
  Pesto-Original (target: < 20% throughput loss).
- [ ] We have a single plot showing throughput-latency curves for all
  four configurations, in the style of Pesto Figure 3.

The first item is complete; the rest are the scope of the evaluation
phase (proposal week 7-8, weeks of April 25 – May 5).

---

## Appendix: How to actually run an experiment

A typical run on the local prototype (single machine, multi-process):

```bash
cd /home/student/CS598FTS/Pequin-Artifact

# 1. Build (already done)
cd src && make all

# 2. Generate replica keys
cd create_keys && ./keygen.sh

# 3. Start replicas (in separate terminals or via experiment-scripts)
./store/server -config-path <config.txt> -group-idx 0 -replica-idx 0 ...

# 4. Run the benchmark client
./store/benchmark/async/sql/rw-sql/rw-sql_client ...

# 5. Collect stats from the per-replica log files
python3 experiment-scripts/regenerate_plots.py <output-dir>
```

For multi-machine (CloudLab) runs, follow `RunningExperiments.md`.

For our heterogeneous configs, the config file format is now:

```
f 1
group
group_f 1
replica host1:7001
replica host2:7002
replica host3:7003
replica host4:7004
replica host5:7005
replica host6:7006
group
group_f 1
replica host7:7001
replica host8:7002
replica host9:7003
replica host10:7004
replica host11:7005
replica host12:7006
```

Note `group_f` per group; all 12 hosts are distinct, so the two shards
have disjoint membership.

---

## Appendix B -- CloudLab deployment runbook (step-by-step)

This is the concrete recipe for running our evaluation on the same
hardware Pesto's authors used (CloudLab `m510`, Utah cluster, Ubuntu
22.04 with our pre-built disk image `JiatongOttoUbuntu22.04-Pesto`).

### B.1 How many nodes?

Sizing depends on which experiment you want to run. Pesto's
`run_multiple_experiments.py` requires *every* host listed in
`server_names` to exist as a CloudLab node, plus at least one client
node. (The `pequin-base` profile co-locates one client per server, so
"6 server" really means "6 server + 6 client".)

| Experiment | Min server nodes | Min client nodes | Notes |
|------------|-----------------|------------------|-------|
| **T1 (homogeneous regression)** | 6 (1 shard × 6 replicas) | 1-6 | Reuses Pesto's stock 1-shard config. 6+1 is enough; 6+6 matches the published run. |
| **T2-T6 (2-shard heterogeneous)** | **12** (2 shards × 6 replicas) | 1-6 | Two **disjoint** shards, each with `f=1` (5f+1 = 6). With only 6 nodes we cannot test cross-shard heterogeneity at the published `f=1`. |
| **F1-F3 (Byzantine faults)** | same as T2 (12) | 1-6 | Faults are simulated in-process via flags; no extra nodes needed. |
| **E6 (3-shard TPC-C)** | 18 (3 × 6) | 1-6 | Optional. |

**Recommendation for our project: instantiate the `pequin-base` profile
with 12 server + 6 client (18 m510) for the cross-shard runs.** If your
quota only allows 6 server nodes you can still complete T1 today and
build evidence for the heterogeneous claims via the 12-node experiment
later. Reserve through CloudLab's *Make Reservation* tab; m510 on Utah
is heavily contended around weekday afternoons (US Mountain time).

You do **not** need a control machine -- driving the experiment from
your laptop works as long as your laptop has SSH access to the Utah
cluster.

### B.2 Starting the CloudLab experiment

1. Log in to https://www.cloudlab.us; click **Experiments → Start
   Experiment**.
2. Pick profile `pequin-base` (or your saved Utah profile that uses our
   `JiatongOttoUbuntu22.04-Pesto` image).
3. Set:
   - *Number of server nodes*: 6 (T1) or 12 (T2-T6).
   - *Server image*: `urn:publicid:IDN+utah.cloudlab.us+image+cs598fts-PG0:JiatongOttoUbuntu22.04-Pesto` (or whichever URN your most recent image build produced).
   - *Client image*: same image is fine.
   - *Use control machine*: unchecked.
4. Name the experiment `pequin` and project `cs598fts` (or whatever
   matches your CloudLab project; the experiment-config `project_name`
   field must match).
5. Wait ~10 min for nodes to image and boot. Confirm with `ssh
   <user>@us-east-1-0.pequin.cs598fts-pg0.utah.cloudlab.us`.

### B.3 Switching the remote on each node to your fork

The disk image ships with the upstream Pequin repo at
`/opt/Pequin-Artifact/`. To run **our** modified code we need to point
that checkout at the fork (`https://github.com/ljtsparky/Pequin-Artifact.git`,
branch `cross-shard-membership`).

On the control node (or once per server -- a small for-loop from your
laptop is fine):

```bash
ssh <user>@us-east-1-0.pequin.cs598fts-pg0.utah.cloudlab.us
cd /opt/Pequin-Artifact

# Inspect the existing remote first; do NOT blow away local work.
git remote -v
git status                # confirm working tree is clean

# Add our fork as a second remote and pull the cross-shard branch.
git remote add fork https://github.com/ljtsparky/Pequin-Artifact.git
git fetch fork
git checkout -b cross-shard-membership fork/cross-shard-membership
```

If you prefer the fork to *replace* `origin` (cleaner once you trust
it), use `git remote set-url origin <fork-url>` instead of adding a
second remote.

To do this across all nodes in one shot from your laptop:

```bash
for h in us-east-1-{0,1,2} eu-west-1-{0,1,2}; do
  ssh <user>@${h}.pequin.cs598fts-pg0.utah.cloudlab.us \
      'cd /opt/Pequin-Artifact && \
       git remote add fork https://github.com/ljtsparky/Pequin-Artifact.git 2>/dev/null; \
       git fetch fork && \
       git checkout -B cross-shard-membership fork/cross-shard-membership'
done
```

For the 12-node 2-shard runs, also include the second shard's hosts
(`ap-northeast-1-{0,1,2}`, `us-west-1-{0,1,2}`).

### B.4 Building on each node

Dependencies are baked into the disk image (jemalloc, taopq, JDK,
libfmt, libsodium, secp256k1, Intel TBB, etc.), so the build is just:

```bash
cd /opt/Pequin-Artifact/src
make -j$(nproc) all
```

Expected output ends with `Finish Building Indicus`. The build takes
~5-7 min on m510. **You must rebuild on every node** because each
server runs the binary from its local disk -- the experiment scripts
do **not** rsync binaries when `remote_bin_directory_nfs_enabled =
false` (which is our default).

A one-liner from your laptop:

```bash
for h in us-east-1-{0,1,2} eu-west-1-{0,1,2}; do
  ssh <user>@${h}.pequin.cs598fts-pg0.utah.cloudlab.us \
      'cd /opt/Pequin-Artifact/src && make -j$(nproc) all' &
done
wait
```

After the build, run our new unit test on at least one node to
confirm the binary is sane:

```bash
cd /opt/Pequin-Artifact/src
./store/pequinstore/tests/membership_test
# Expect: "Passed: 34, Failed: 0"
```

### B.5 What runs on each node

You do **not** start servers and clients by hand --
`run_multiple_experiments.py` does that for you. But for the mental
model:

| Node | Role | What the script launches |
|------|------|--------------------------|
| `us-east-1-0` | **Shard 0 replica 0** | `store/server -config-path shard.config -group-idx 0 -replica-idx 0 -num_groups 1 -num_shards 1 [...]` |
| `us-east-1-1` | Shard 0 replica 1 | same with `-replica-idx 1` |
| `us-east-1-2` | Shard 0 replica 2 | `-replica-idx 2` |
| `eu-west-1-0` | Shard 0 replica 3 | `-replica-idx 3` |
| `eu-west-1-1` | Shard 0 replica 4 | `-replica-idx 4` |
| `eu-west-1-2` | Shard 0 replica 5 | `-replica-idx 5` |

For the 2-shard heterogeneous runs, the next 6 nodes
(`ap-northeast-1-{0,1,2}`, `us-west-1-{0,1,2}`) run **shard 1**, with
`-group-idx 1 -num_shards 2 -num_groups 2`. The `shard.config` file is
generated by the script from the JSON config's `server_names` list and
shipped to every node via SCP.

Client nodes (`client-0-0` through `client-N-N`) run
`store/benchmark/async/benchmark` with the workload args from the
JSON. By default each client node hosts 8 client processes
(`client_processes_per_client_node`).

**You drive everything from your laptop with one command:**

```bash
cd /opt/Pequin-Artifact   # or wherever you cloned the fork locally
python3 experiment-scripts/run_multiple_experiments.py \
        experiment-configs/Pesto/2-Microbenchmarks/Test-CrossShard.json
```

The script will (a) SCP binaries and the generated `shard.config` to
every node, (b) start servers, (c) start clients, (d) wait for
`client_experiment_length + ramp_up + ramp_down` seconds, (e) collect
per-replica logs, (f) write `stats.json` and PNG plots to
`base_local_exp_directory`.

### B.6 Generating the heterogeneous test config

We will create a new config under
`experiment-configs/Pesto/2-Microbenchmarks/CrossShard/` for each test.
T2 is the simplest -- copy `Test.json` and change:

```json
"num_shards": [2],
"num_groups": [2],
"server_names": [[
   "us-east-1-0", "us-east-1-1", "us-east-1-2",
   "eu-west-1-0",  "eu-west-1-1",  "eu-west-1-2",
   "ap-northeast-1-0", "ap-northeast-1-1", "ap-northeast-1-2",
   "us-west-1-0", "us-west-1-1", "us-west-1-2"
]],
"server_regions": [{
   "us-east-1": ["us-east-1-0", "us-east-1-1", "us-east-1-2"],
   "eu-west-1": ["eu-west-1-0", "eu-west-1-1", "eu-west-1-2"],
   "ap-northeast-1": ["ap-northeast-1-0", "ap-northeast-1-1", "ap-northeast-1-2"],
   "us-west-1": ["us-west-1-0", "us-west-1-1", "us-west-1-2"]
}],
```

The first 6 hosts become shard 0; the next 6 become shard 1. Because
the four "regions" are distinct hosts on the same Utah LAN, the
membership of the two shards is fully **disjoint** -- exactly the
sister-replica-free deployment our protocol is designed for.

### B.7 Byzantine fault tests on CloudLab

The Pesto codebase already exposes three flags that simulate
Byzantine-style misbehaviour at the replica level. They are toggled
via the experiment JSON inside `replication_protocol_settings`:

| Flag | Meaning | Models |
|------|---------|--------|
| `simulate_replica_failure: true` | The replica drops every message it receives (`server.cc:421`). | Crash failure / silent peer. |
| `simulate_inconsistency: true` | The replica selectively drops *prepare* and *commit* messages for transactions whose `client_id % n` matches a target (`server.cc:2013`). The system must still commit via slow-path quorums. | Byzantine equivocator that omits replies. |
| `inject_failure_proportion: 0..1` + `_inject_failure_type: "client-crash"` | Faulty client crashes mid-transaction with a configurable probability. | Stalling Byzantine client (Pesto §7.4). |

**F1 -- Crash failures under heterogeneity** (uses T2 config):

```jsonc
"replication_protocol_settings": [{
   ...,
   "simulate_replica_failure": true,
   "_note": "Set on shard0/replica5 and shard1/replica5 only via num_failures hook"
}]
```

The `simulate_replica_failure` flag applies to whichever replica
indices are listed under `num_failures` / `num_byz_clients` in the
config (see `experiment-scripts/utils/experiment_util.py` for how the
script picks which replica processes start with the flag set). For our
heterogeneous run we set `num_failures = 1 per shard` so that the last
replica of each shard is silent -- this matches our claim that the
remaining `4f+1 = 5` honest replicas can still drive a slow-path
commit.

**F2 -- Byzantine equivocation under heterogeneity** (uses T2 config):

```jsonc
"replication_protocol_settings": [{
   ...,
   "simulate_inconsistency": true
}]
```

This is the most informative test -- it triggers Pesto's
cooperative-fallback path (Basil §4.5) and is the real proof that our
SS-CERT exchange + per-group quorum still preserves Byz-serializability
when 1 replica per shard actively misbehaves.

**F3 -- Stalling Byzantine client across shards** (uses T2 config):

```jsonc
"inject_failure_proportion": 0.1,
"inject_failure_ms": 0,
"inject_failure_freq": 100,
"_inject_failure_type": "client-crash"
```

10 % of cross-shard transactions abort mid-flight. Recovery uses
Basil's view-change / fallback path (inherited unchanged by Pesto and
by us). The pass criterion is that the system continues to commit
non-failing transactions and that no DSG cycle appears in the offline
check (§3.4).

> **What "correctness verified" looks like in practice**: each F1-F3
> run produces a `stats.json` whose `combined.tput_s_honest` is > 0
> (honest clients still make progress) **and** the per-replica log
> files, when fed through our DSG checker, contain no cycle. We
> consider F2 the strongest single piece of evidence because it
> exercises the new SS-CERT verification code under live Byzantine
> behaviour.

### B.8 Cleanup and image refresh

When you finish a session:

```bash
# Optional: snapshot the (now compiled-with-our-code) state into a
# refreshed disk image so you don't have to rebuild on each new
# experiment instantiation.
# CloudLab UI -> Experiment -> "Create Disk Image" on us-east-1-0,
# overwrite the existing JiatongOttoUbuntu22.04-Pesto image.
```

Remember the caveats from `cloudlab_project_timeline.md`: `~/` is **not**
preserved in the image, so push commits to GitHub before terminating
the experiment.
