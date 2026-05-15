# CS 598 FTS -- Removing the Sister-Replica Assumption from Pesto

**Course:** CS 598 FTS (Spring 2026), UIUC
**Authors:** Jiatong Li ([jl180@illinois.edu](mailto:jl180@illinois.edu)),
            Otto Piramuthu ([obp2@illinois.edu](mailto:obp2@illinois.edu))
**Branch:** [`cross-shard-membership`](../../tree/cross-shard-membership) of this fork
**Upstream:** [Pesto SOSP'25 artifact](https://github.com/fsuri/Pequin-Artifact)
            (we forked at `main`; all our changes live on the
            `cross-shard-membership` branch)

> The course report (PDF + LaTeX source) and the per-experiment
> writeups are submitted **separately** through the course submission
> system. This repository contains only the code, orchestrator, and
> analysis scripts.

---

## 1. What this project does

Pesto's cross-shard coordination assumes that **every trust authority
operates a replica in every shard** (Appendix B.10 of the Pesto paper).
This "sister-replica" assumption is convenient but unrealistic for
federated, multi-organization deployments.

We **remove** that assumption by introducing:

1. **Shard Membership Certificates** -- each shard publishes a
   cryptographic attestation of its replica set (group ID, fault budget
   `f`, public keys, BLAKE3 digest). Peer shards load it at bootstrap.
2. **SS-CERT v3-STRICT** (called *Strict SS-CERT* in the report) --
   cross-shard snapshot certificates whose digest is content-bound to
   the query result hash, requiring **`2f+1` distinct Ed25519
   signatures** that all attest to the same content. The receiving shard
   verifies the cert using the sender's MembershipCert.
3. **Heterogeneous-quorum runtime** -- per-shard `n` and `f` throughout
   the protocol stack (replaces the single global `n` assumption).

We implement on top of the official Pesto artifact and evaluate on a
38-node CloudLab cluster spanning `f` in {1, 2, 3}.

## 2. Headline results

(Full numbers are in the course-report PDF.)

- Removing the sister-replica assumption costs **<= 5%** throughput at
  the same fault budget.
- At low load (NC=6), original Pesto is 58% faster than our extension
  (the cost of the extra crypto). At medium load (NC=12) they tie.
  **At high load (NC=24), our extension delivers 3.85x** the throughput
  of original Pesto, because the content-bound histogram filter smooths
  cross-replica timing variance.
- Across ~250 experiments and ~1.05 million v3-STRICT verifications
  under honest and Byzantine workloads, **zero spurious cert accepts**.
  Cross-shard atomicity audit reported **zero partial-commit
  violations** across 6,682 cross-shard TPC-C transactions at f=1,2,3.

## 3. Repository layout

```
cs598_project/
├── README.md                     <-- this file
├── orchestrator/                 <-- CloudLab experiment drivers (bash)
│   ├── run_byzantine_experiment.sh   <-- main entry point
│   ├── run_heterogeneous_experiment.sh
│   ├── setup_18_nodes.sh
│   └── lab_ssh.txt.template          <-- copy + fill with your hostnames
└── scripts/                      <-- per-result analysis / verification tools
    ├── perf_analyze.py               <-- extract tput/latency/crypto micros
    ├── l2_audit.py                   <-- cross-shard atomicity audit
    ├── dsg_check.py                  <-- per-client invariant check (L1)
    ├── mini_elle.py                  <-- Adya G0/G1/G2 cycle check
    ├── apply_wan_delay.sh            <-- tc/netem WAN simulation
    ├── elle_check.sh
    ├── generate_ppt_figures.py
    ├── install_node_deps.sh
    ├── redeploy_18_nodes.sh
    └── test_mini_elle.sh
```

Source-code changes for the extension itself are **inline in the rest
of the repo**, on the `cross-shard-membership` branch. The most-touched
files (from `git diff main..cross-shard-membership`):

| File | What we added |
|------|---------------|
| `src/store/pequinstore/membership.{h,cc}` | Shard membership cert generator + store |
| `src/store/pequinstore/server.cc` | `GenerateSnapshotVote`, `VerifyForeignSSCert`, self-test, micros timers + bucket histograms |
| `src/store/pequinstore/querysync-server.cc` | Content-bound v3 vote in `SendQueryReply`; twin-byz mode |
| `src/store/pequinstore/querysync-client.cc` | Histogram-majority + harvest-before-done cert assembly |
| `src/store/pequinstore/common.{h,cc}` | Per-group `QuorumSize`, `IsReplicaInGroupHeterogeneous`, `VerifySnapshotCert` |
| `src/store/pequinstore/pequin-proto.proto` | `SnapshotVote.signed_digest` field |
| `src/store/pequinstore/query-proto.proto` | `v3_vote` field in `QueryResultReply` |
| `src/store/server.cc` | New CLI flags: `--pequin_drop_cross_shard_writeback`, `--pequin_twin_replica` |

## 4. How to reproduce

### 4.1 Allocate a CloudLab cluster

We used the Pesto profile (see upstream
[`CloudlabSetup.md`](../CloudlabSetup.md)) with **38 nodes**
(`m400`/`c220g2` mixed) on Utah. For `f=1` deployments 18 nodes
suffice (12 servers + 6 clients).

Bake a disk image once after building Pesto + our extension at
`/opt/Pequin-Artifact` (the rebuild step is automated by
`orchestrator/setup_18_nodes.sh`).

### 4.2 Build the binary

```bash
cd /opt/Pequin-Artifact
git checkout cross-shard-membership
source /opt/intel/oneapi/setvars.sh    # for libtbb
cd src && make -j 4 store/server store/benchmark/async/benchmark
```

### 4.3 Configure node list

```bash
cd cs598_project/orchestrator
cp lab_ssh.txt.template lab_ssh.txt
# fill lab_ssh.txt with one "ssh user@host" line per node
```

### 4.4 Run an experiment

The orchestrator takes env-variable overrides for everything:

```bash
# f=1 heterogeneous baseline (paper's headline number, NC=6, rw-sql):
F_PER_SHARD=1 SISTER_REPLICA=false \
  NUM_TABLES=2 NUM_OPS=2 DURATION=60 BENCHMARK=rw-sql BYZ_PER_SHARD=0 \
  PEQUIN_EAGER=false SCAN_AS_POINT=false QUERY_MESSAGES=query-all \
  NUM_CLIENTS=6 \
  bash run_byzantine_experiment.sh

# Sister-replica vs heterogeneous ablation at f=2:
F_PER_SHARD=2 SISTER_REPLICA=true  ... bash run_byzantine_experiment.sh
F_PER_SHARD=2 SISTER_REPLICA=false ... bash run_byzantine_experiment.sh

# Original Pesto comparison (uses the upstream binary at
# /opt/Pequin-Artifact-Origin/src/store/server):
USE_ORIGIN=true F_PER_SHARD=1 NUM_CLIENTS=24 ... bash run_byzantine_experiment.sh

# Byzantine modes:
BYZ_PER_SHARD=1 BYZ_REPLICA_MODE={inconsistency,twin_sig,drop_xshard} ...

# WAN simulation (auto-detects interface per node):
bash ../scripts/apply_wan_delay.sh apply 25
... bash run_byzantine_experiment.sh
bash ../scripts/apply_wan_delay.sh remove
```

Each run lands in `pesto-results/<TIMESTAMP>/` with `run_params.txt`,
per-server stats JSON, per-client logs, and an Elle history file.

### 4.5 Analyze a run

```bash
# Throughput, P50/P95/P99, crypto micros:
python3 cs598_project/scripts/perf_analyze.py pesto-results/<TS>/

# Cross-shard atomicity (L2 audit, runs on TPC-C results):
python3 cs598_project/scripts/l2_audit.py pesto-results/<TS>/

# Per-client invariants (L1):
python3 cs598_project/scripts/dsg_check.py pesto-results/<TS>/
```

## 5. License

Same as upstream Pesto (see [`../LICENSE`](../LICENSE)).
