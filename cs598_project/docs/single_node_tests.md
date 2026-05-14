# Single-Node Tests — Stage Summary

This document records the single-node validation we ran on a CloudLab `m510`
(Clemson) before scaling out to the 12-server / 6-client cross-shard
deployment. It serves both as a runbook (what to invoke + what to expect)
and as a stage report (what passed, what's known-broken upstream, why we
proceed).

---

## 0. Get the code on a fresh CloudLab node

**Fork URL**: `https://github.com/ljtsparky/Pequin-Artifact.git`
(SSH form: `git@github.com:ljtsparky/Pequin-Artifact.git`)
**Branch**: `cross-shard-membership`

### 0.1 If `/opt/Pequin-Artifact/` already exists from the disk image (preferred)

The CloudLab image `JiatongOttoUbuntu22.04-Pesto` ships with a clone at
`/opt/Pequin-Artifact/`. Just point its `origin` at our fork and pull our
branch — no rebuild of dependencies needed.

```bash
cd /opt/Pequin-Artifact
git remote -v                                       # see current origin
git remote set-url origin git@github.com:ljtsparky/Pequin-Artifact.git
git fetch origin
git checkout -B cross-shard-membership origin/cross-shard-membership
git log --oneline -3                                # confirm head is ours
```

Expected `git log` head:
```
3771f1cd  Add aggregate runner for upstream Pequin unit tests + ours
7d392a75  .gitignore: stop tracking compiled test binaries
b659a0d3  smoke_test_pequin.sh: dump full logs on failure...
```
(The exact top commit may be newer if we've pushed since this doc was written.)

### 0.2 If you need a fresh clone (e.g., side-by-side with upstream for baseline)

```bash
cd /opt
git clone git@github.com:ljtsparky/Pequin-Artifact.git Pequin-Artifact-Mine
cd Pequin-Artifact-Mine
git checkout cross-shard-membership
```

For the baseline upstream we used `git clone https://github.com/cmu-db/Pequin-Artifact.git Pequin-Artifact-Origin` (or whatever the original upstream URL is) and kept it next to ours so `run_unit_tests.sh` can be pointed at either tree.

### 0.3 Daily incremental update

Once a branch is checked out, just:

```bash
cd /opt/Pequin-Artifact
git pull            # fast-forwards cross-shard-membership to latest
```

Since `git pull` only changed files trigger rebuilds, an `-MD`-tracked
incremental `make -j$(nproc)` after a pull typically takes seconds (a
single .cc) to ~2 minutes (a widely-included header). No need to rebuild
from scratch unless you `make clean`.

### 0.4 Known build caveat: first `make -j` may fail, second succeeds

When building from a clean tree (or after `make clean`) with parallel
jobs (`make -j$(nproc)`), the **first build can fail** with a
"file not found" or "no such header" style error pointing at a
generated protobuf header (`*.pb.h`). The **second** invocation then
finishes cleanly and reports `Finish Building Indicus`.

Cause: upstream's `Rules.mk` doesn't fully declare the dependency from
`*.cc` files on the corresponding `*.pb.h` produced by `protoc`. With
`-j`, a `g++ -c foo.cc` job can launch concurrently with the `protoc`
job that should produce a header it `#include`s; the g++ reads a
half-written file or no file at all. On the second run, the header is
already on disk so the race is gone.

**What to do**: just run `make -j$(nproc) all` again. If it succeeds the
second time, the build is genuinely good — Make wouldn't claim
"up-to-date" if any `.o` were missing. To be extra safe:

```bash
make -j$(nproc) all 2>&1 | tee /tmp/build.log
# If there were errors first time:
make -j$(nproc) all 2>&1 | tee -a /tmp/build.log
# Sanity check: every test binary now exists
ls store/pequinstore/tests/membership_test \
   store/pequinstore/tests/{tbb_test,proto_bench,compression_test,snapshot_test,table_loader_test,sql_interpreter_test,table_store_interface_test} \
   store/server store/benchmark/async/benchmark
```

If `ls` finds all binaries with no "No such file" errors, you're done.
For a permanent fix you'd patch `Rules.mk` to declare every `.o`
dependency on the relevant `.pb.h` explicitly — out of scope for this
project.

### 0.5 SSH key setup (one-time, only if you used HTTPS before)

The image has SSH support but no GitHub key by default. To push:

```bash
ssh-keygen -t ed25519 -C "jl180@illinois.edu" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub      # paste into github.com → Settings → SSH keys
ssh-keyscan -t rsa,ed25519 github.com >> ~/.ssh/known_hosts
ssh -T git@github.com          # expect: "Hi ljtsparky! You've successfully..."
```

`~/.ssh/` is **NOT** persisted across CloudLab image reboots, so this
needs to be redone every time you spawn a fresh experiment from the
image (or bake it into the image — but be careful not to publish the
private key in a public image).

---

## 1. What we set out to verify

After committing the cross-shard heterogeneous membership work
(`1847659a Add cross-shard heterogeneous membership support to Pesto`),
we wanted **independent evidence** that:

1. Our new code (membership cert, per-group quorum, heterogeneous ID
   mapping, SS-CERT verification) is functionally correct.
2. The patch did **not** regress any upstream Pequin component.
3. The build environment (`/opt/Pequin-Artifact/`, `/opt/dependencies/`,
   `/opt/pesto-deps/`, Intel TBB, JDK) on the CloudLab disk image is
   complete enough to bake a fresh image for the 18-node experiment.

The strategy: small, fast, reproducible tests on **one** node before
spending a 12+6-node experiment slot.

---

## 2. Scripts (both committed in our fork)

| Script | Purpose | Time |
|--------|---------|------|
| `src/store/pequinstore/tests/membership_test` | Our 34 hand-written assertions covering the new code paths. Runs in isolation, no network. | ~5 s |
| `src/0_local_test_outputs/configs/run_unit_tests.sh` | Sweeps **all 8 test binaries** in `src/store/pequinstore/tests/` (ours + upstream). Reports PASS / SKIP / FAIL with per-test logs. | ~90 s |
| `src/0_local_test_outputs/configs/smoke_test_pequin.sh` | 6-replica loopback Pesto run with the legacy `rw` benchmark. **Known to segfault** because legacy `rw` is unmaintained on the modern `pequin` protocol path; *not* a regression we caused. Kept for completeness. | ~20 s (then crashes) |

---

## 3. How to run on a CloudLab node

```bash
# 0. Make sure you have the binaries built (skip if image already has them)
cd /opt/Pequin-Artifact/src
make -j$(nproc) -k all      # full build, ~5–7 min on m510 with 8 cores

# 1. The new code's own assertion suite
./store/pequinstore/tests/membership_test

# 2. Aggregate sweep over all 8 test binaries
bash 0_local_test_outputs/configs/run_unit_tests.sh
```

Optional baseline check (only if you want 100% rigor):

```bash
# 3. Same script against pristine upstream — confirms identical failure pattern
bash /opt/Pequin-Artifact-Origin/src/0_local_test_outputs/configs/run_unit_tests.sh
```

---

## 4. Expected output

### 4.1 `membership_test` — must be 34/34 PASS

```
=== Cross-Shard Heterogeneous Membership Test Suite ===

[TEST] PerGroupAccessors
  [PASS] GroupN(0) == 5
  [PASS] GroupN(1) == 6
  [PASS] config recognized as heterogeneous

[TEST] GlobalReplicaIdMapping
  [PASS] Group 0 idx 0 -> global 0
  [PASS] Group 0 idx 4 -> global 4
  [PASS] Group 1 idx 0 -> global 5
  [PASS] Group 1 idx 5 -> global 10
  [PASS] Round-trip for (group, idx) = (0,0) via global id 0
  ... (11 round-trips)

[TEST] PerGroupQuorums
  [PASS] QuorumSize(group 0) == 5
  [PASS] SlowCommitQuorumSize(group 0) == 4
  [PASS] SlowAbortQuorumSize(group 0) == 2
  [PASS] FastQuorumSize(group 0) == 6

[TEST] IsReplicaInGroupHeterogeneous
  [PASS] Global 0 in group 0
  [PASS] Global 4 in group 0
  [PASS] Global 5 NOT in group 0
  [PASS] Global 5 in group 1
  [PASS] Global 10 in group 1
  [PASS] Global 0 NOT in group 1

[TEST] MembershipCertVerification
  [PASS] Tampered cert should fail VerifyCert
  [PASS] MembershipManager has cert for group 0
  [PASS] MembershipManager returns cert for group 0
  [PASS] MembershipManager returns null for unknown group
  [PASS] Stale version not overwritten
  [PASS] Newer version overwrites older

=== Summary ===
Passed: 34
Failed: 0
```

### 4.2 `run_unit_tests.sh` — expected pattern

```
membership_test                   PASS  (cross-shard membership cert + per-group quorums (OURS))
tbb_test                          TIMEOUT (>60s)
proto_bench                       PASS  (protobuf serialization micro-benchmark)
compression_test                  PASS  (payload compression round-trip)
snapshot_test                     PASS  (snapshot manager unit tests)
table_store_interface_test        FAIL  (exit 134)
table_loader_test                 PASS  (loads on-disk schema (needs schema file))
sql_interpreter_test              FAIL  (exit 134)

================ Summary ================
  PASS:  5
  SKIP:  0
  FAIL:  3
```

The **3 FAILs are pre-existing upstream issues** (verified by running the
same script against `/opt/Pequin-Artifact-Origin/`, where they fail
identically at the same code locations). See §6 below for the per-test
explanation.

### 4.3 `smoke_test_pequin.sh` — expected to fail, document only

The 6-replica loopback run will SEGFAULT after the client warmup
completes. This is **not** a regression: the `--benchmark rw` legacy KV
workload combined with the `--protocol pequin` modern protocol is an
unmaintained code combination in upstream. Pesto's actual experiments use
`benchmark_type: sql_bench` / `benchmark_name: rw-sql` via the
`experiment-scripts/run_multiple_experiments.py` harness, which is the
maintained path and what we use for the 18-node evaluation.

---

## 5. Verdict from this stage

✅ **Zero regression.** The new cross-shard code paths pass all 34 of
their own assertions, and our changes do not break any upstream component
that was previously working.

✅ **Build environment is complete.** Every test binary linked and ran
(failures are at the application logic layer, not at dynamic-loader /
missing-symbol level), confirming all dependencies in
`/opt/dependencies/` and `/opt/pesto-deps/` are present.

✅ **Image is safe to bake.** Proceed to CloudLab UI → "Create Disk
Image" → overwrite `JiatongOttoUbuntu22.04-Pesto`.

---

## 6. Why the 3 FAILs are NOT our regression

For the record, here is a brief root-cause for each FAIL and why it does
not implicate either our code or our build:

### 6.1 `tbb_test` — upstream demo with intentional deadlock

`src/store/pequinstore/tests/tbb_test.cc` line ~48:

```cpp
testMap.insert(t1, dummyString);   // takes write lock t1
t1->second = true;
// t1.release();                   // ← release intentionally commented out
...
testMap.find(t3, dummyString);     // tries read lock → blocks on t1 forever
```

No exit logic. This is a scratch/demo binary upstream wrote to explore
TBB accessor semantics, not a real PASS/FAIL test. A 60-second timeout
in `run_unit_tests.sh` reports it as TIMEOUT. Not a regression, not a
missing dependency.

### 6.2 `sql_interpreter_test::test_predicates` — upstream test/code mismatch

`sql_interpreter_test.cc:556` registers columns `{"age", "name", "color"}`
but the test predicates use positional names `col1`, `col2`, `col3`:

```cpp
std::vector<std::string> col_names = {"age", "name", "color"};
...
std::string pred = "col1 = 5";                         // PASSes (line 569)
pred = "col1 >= 5 AND col2 = 'neil'";                  // FAILs at line 588
```

The first (single-clause) predicate passes; the second (with `AND`)
fails. Either Peloton's predicate evaluator regressed in handling
positional-style aliases under conjunctions, or the test was never
updated when column-naming convention changed. Either way it is upstream
code, untouched by us.

### 6.3 `table_store_interface_test` — same Peloton SQL layer

The binary is release-stripped, so the backtrace is hex-only. But it
links the same `LIB-pequin-store` that `sql_interpreter_test` uses, and
both abort at the same hex offsets in the table/SQL interface code.
Almost certainly the same Peloton predicate-evaluation bug surfacing in
a different call site. Not our code.

---

## 7. Dependency check vs Installation.md

Cross-checked our `/opt` layout against
`/opt/Pequin-Artifact/Installation.md` — every required dependency is
present:

| Installation.md requires | Our layout | Status |
|--------------------------|-----------|--------|
| libsodium / libgflags / libssl / libevent / libfmt | apt-installed | ✅ |
| jemalloc | `/opt/dependencies/` | ✅ |
| taopq | `/opt/pesto-deps/` | ✅ |
| nlohmann/json | `/opt/pesto-deps/` | ✅ |
| protobuf 3.5.1 | system | ✅ |
| cryptopp 8.2 | system | ✅ |
| secp256k1 | system | ✅ |
| BLAKE3 | `/usr/local/lib/libblake3.so` | ✅ |
| ed25519-donna | `/usr/local/lib/libed25519_donna.so` | ✅ |
| Intel TBB (oneAPI) | `/opt/intel/oneapi/` (sourced via `/etc/bash.bashrc`) | ✅ |
| Peloton third-party (libpg_query, libcuckoo, date, adaptive_radix_tree) | `/opt/pesto-deps/` | ✅ |
| OpenJDK 11 (BFTSmart) | `/usr/lib/jvm/java-11-openjdk-amd64`, `LD_LIBRARY_PATH` set | ✅ |

Hard evidence we are not missing a `.so`: every test binary actually
runs — it gets to the application-level assertion / panic, which is only
possible after dynamic linking and library initialisation succeed. A
missing dependency would surface as `cannot open shared object file` or
a segfault inside the dynamic loader before any user code executes.

---

## 8. Next stage — what changes when we move to 12 server + 6 client

Single-node tests above only exercise the **per-replica** code (data
structures, crypto, configuration parsing, single-shard membership). The
12-server / 6-client experiment is what actually exercises:

- Cross-shard SS-CERT exchange
- Per-group quorum thresholds across two disjoint shards
- T_global frontier computation across shards
- The full Pesto protocol (Phase1 / Phase2 / Writeback) under load

That is what `evaluation_and_correctness.md` (T2-T6, F1-F3, E1-E6) drives
through the `experiment-scripts/run_multiple_experiments.py` harness with
`benchmark_name: rw-sql` (the maintained workload path).

To get there:

1. CloudLab UI → "Create Disk Image" on the current single-node
   experiment → overwrite `JiatongOttoUbuntu22.04-Pesto`. ~15 min.
2. Terminate the single-node experiment.
3. Spin up 18 m510 nodes (12 server + 6 client) using the refreshed
   image, on the same Clemson cluster.
4. SSH into `node0` (or whichever the script names) and run the
   cross-shard JSON config through `run_multiple_experiments.py`.

The cross-shard JSON config + heterogeneous shard map will be added in a
follow-up commit and documented in `evaluation_and_correctness.md`
Appendix B.6.
