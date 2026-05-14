# Checkpoint — 2026-05-11 (v2.3 GREEN)

> Hand-off snapshot for resuming on another machine.
> **Latest pushed commit:** `5dd95967` (SS-CERT v2.3 + T13 adversarial flag)

## Headline: SS-CERT end-to-end LIVE 🎉

After 7 commits of debugging (v0 → v2.3) the SS-CERT path runs at full
speed and discriminates correctly between honest and malicious certs.

| Check | Result | Path |
|-------|--------|------|
| **T12** honest baseline | **68 102 / 68 102 verified OK (100%)** | `pesto-results/20260511T203525Z/AGGREGATE.md` |
| **T13** `one_vote`   | **0 OK / 70 068 FAIL (correct reject)** | `pesto-results/exp_t13_adversarial/` |
| **T13** `wrong_sig`  | **0 OK / 68 586 FAIL** | same |
| **T13** `wrong_group`| **0 OK / 71 046 FAIL** | same |

This is the gold standard: 100% precision, 0 false negatives on bad
certs; 100% pass on well-formed certs. Verifier is sound + complete on
the 3 anomaly classes we tested.

## All commits since the original SS-CERT v0

| SHA | What |
|-----|------|
| `ef703550` | SS-CERT v0: HandleSync verify call + `membership_cert_loaded` |
| `0ff41eec` | Het bug 1: `server.cc:553` use `GroupN(group)` |
| `ef8d96d4` | Het bug 2+3: tcptransport.cc:335 + `replica_total` |
| `572b46e4` | SS-CERT v1: GenerateSnapshotVote + self-test |
| `9ea8822a` | SS-CERT v2: wire path (votes attached, certs assembled) |
| `f956f3e8` | SS-CERT v2.1: embed `signed_digest` (proto non-canonical fix) |
| `432363d3` | SS-CERT v2.2: client-side counters (`client_cert_*`) |
| `77c13b05` | **SS-CERT v2.3: sign query identity, not local_ss** |
| **`5dd95967`** | **T13 `--pequin_inject_bad_ss_cert` adversarial flag** |

The full debugging trail (each version's diagnosis → fix) lives in
`pesto-results/20260511T203525Z/AGGREGATE.md` § "Bug taxonomy".

---

## Done

### Phase 1 — Pre-bake (single-node)
- `docs/image_bake_plan.md` (master plan)
- `scripts/install_node_deps.sh` (canonical recipe)
- Single-node compile + 34/34 membership_test
- TPC-C 10-warehouse data pre-gen (657 MB)
- Elle CLI 0.1.9 jar download

### Phase 2 — 18-node bring-up & first 3 experiments
- Image survived re-launches (binaries / TPCC data / Elle jar all present after
  fresh CloudLab profile launch)
- **Exp A** (`pesto-results/20260510T035557Z/`): TPC-C cross-shard, 372 cross-shard /
  7 174 total. Fixed `--partitioner=warehouse` flag missing.
- **Exp B** (`pesto-results/het-20260510T055450Z/`): heterogeneous + byzantine.
  17 servers (n=6 + n=11) 0 panic. Caught 3 latent het bugs.
- **Exp C** (`pesto-results/exp_c_real_elle/`): real Elle CLI vs mini_elle.
  Both honest + byz histories `valid? true` under serializable / strict-
  serializable / strong-snapshot-isolation.

### Phase 3 — Performance variance
- 3 reps × 90s TPC-C cross-shard: **293.4 ± 10.9 tx/s** (3.7% variance)

### Phase 4 — SS-CERT counter visibility (T1–T4)
- Server `--stats_file` flag, dump on Cleanup
- `GenerateSnapshotVote` on every reply (counter)
- Server startup self-test invokes `VerifyForeignSSCert` (counter)
- Per-replica counters proven: `membership_cert_loaded=12`,
  `ss_cert_self_test_runs=12`, `ss_cert_verifications_failed=12`

### Phase 5 — End-to-end SS-CERT (T8–T13)
- T8: identified `--pequin_query_eager_exec=false --scan_as_point=false`
  combo to force the sync-proposal path (`handle_sync_total` 0 → 133k)
- T9: extended `SyncReply` proto with `vote = 5`
- T10: server attaches vote to `SyncReply.vote`
- T11: client per-PendingQuery vote collection + cert assembly
- v2 → v2.3 debugging:
  - v2: certs assembled but ALL rejected (protobuf non-canonical digest mismatch)
  - v2.1: server embeds `signed_digest` in vote so client doesn't recompute
  - v2.2: client-side debug counters localize gap (`client_cert_built = 0`!)
  - v2.3: sign over query identity, not local_ss → 100% pass
- **T12 GREEN**: 85k verifications, 100% pass
- **T13 GREEN**: 3 injection modes × ~70k requests, 100% reject; honest path 100% pass

---

## Todo (in priority order)

### Tier 1 — DONE ✅

### Tier 2 — TPC-C Adya cycle check
- TPC-C currently has no Elle history hooks. Mapping TPC-C SQL to rw-register
  model isn't 1:1; the cleanest approach is per-warehouse 'append on
  o_id' modeling for NewOrder.
- Add `EllInit/EllNowNs/EllEmit` to `new_order.cc`, `payment.cc`,
  `delivery.cc` at txn boundary.
- Re-run TPC-C cross-shard with `--elle_history_path=`, then mini_elle.py
  + real Elle CLI on the captured cross-shard history.

### Tier 3 — Cross-ShardClient cert sharing (true cross-shard)
- v2.3 cert is from group=G attached to a request also to group=G.
  Proves verifier on real wire but origin == destination shard.
- For true cross-shard: parent `Client` object routes certs between
  ShardClients. When a transaction spans groups, cert from one group is
  attached to a request to another.
- Sketch: `Client::OnQueryReply(group, cert)` stores per-group cert;
  on send to `group_X`, pick the most-recent cert from a different group.

### Tier 4 — Performance sweep
- Single perf data point so far: 293 ± 11 tx/s at 6 clients.
- Sweep `N_clients ∈ {1, 6, 12, 24}` × `cross-shard% ∈ {0, 25, 50, 100}` × 3 reps.
  Needs orchestrator param `NUM_CLIENTS` + more client nodes.
- Latency CDF: parse client logs for per-txn ns, plot p50/p95/p99.

### Tier 5 — Fail-closed v3
- Today the verifier is observability-only: log + count, but never drop
  the proposal on cert failure. Production-grade BFT needs to refuse to
  process a sync proposal whose foreign cert doesn't verify.
- Add a `--pequin_fail_closed_ss_cert` flag that returns early from
  `HandleSync` on `ss_cert_verifications_failed`. Re-run T13 to confirm
  throughput drops to ~0 on the 3 injection modes.

### Tier 6 — Live membership reconfiguration (research-level, out of scope)

---

## Repository state

| Artifact | Where |
|----------|-------|
| Local working tree | `/home/student/CS598FTS/` (no git) |
| Pesto fork | `/home/student/CS598FTS/Pequin-Artifact/` (git, branch `cross-shard-membership`) |
| Latest pushed commit | **`5dd95967`** |
| Chat log this session | `.claude_chat_log.jsonl` (33 MB) — included in the bundle |
| Bundle zip | `CS598FTS_checkpoint_*.zip` at repo root |

## Resume on a new machine

```bash
# 1. Unzip + read this checkpoint
unzip CS598FTS_checkpoint_*.zip && cd CS598FTS
cat docs/CHECKPOINT_2026-05-11.md

# 2. Re-clone Pesto fork (excluded from zip — 3.7 GB)
git clone https://github.com/ljtsparky/Pequin-Artifact.git
cd Pequin-Artifact && git checkout cross-shard-membership
git rev-parse HEAD   # should be 5dd95967 or newer
cd ..

# 3. CloudLab relaunches give fresh IPs each time. After spinning up the
#    18-node profile, paste the 18 hosts into lab_ssh.txt:
nano lab_ssh.txt   # or edit by hand

# 4. SSH plumbing on the new node set
bash setup_18_nodes.sh

# 5. Each node's disk image (if saved earlier) has the binaries from an
#    older commit; pull + rebuild to get to current HEAD:
parallel -j6 'ssh -o BatchMode=yes {} \
    "cd /opt/Pequin-Artifact && git pull origin cross-shard-membership && \
     source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1 && \
     cd src && make -j8 store/server store/benchmark/async/benchmark"' \
    :::: <(awk 'NF>=2 && $1=="ssh" {print $2}' lab_ssh.txt)

# 6. Re-verify T12 (should be ~100% pass):
PEQUIN_EAGER=false SCAN_AS_POINT=false BENCHMARK=rw-sql NUM_TABLES=2 \
    DURATION=20 bash run_byzantine_experiment.sh

# 7. Re-verify T13 (should be 100% reject on all 3 modes):
for m in one_vote wrong_sig wrong_group; do
    INJECT_BAD_SS_CERT=$m PEQUIN_EAGER=false SCAN_AS_POINT=false \
        BENCHMARK=rw-sql NUM_TABLES=2 DURATION=15 \
        bash run_byzantine_experiment.sh
done
```
