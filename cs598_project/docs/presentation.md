# CS 598 FTS — Final Presentation

Title: Removing the Sister-Replica Assumption from Pesto
Speaker: Jiatong Li (jl180@illinois.edu)
Length: ~10–11 minutes total
Slides 1 + 2 + 3a/b/c → ~4 min  (problem framing)
Slides 4 + 5 + 6 + 7 → ~4 min   (testbed + 4 experiments)
Slides 8 + 9 + 10 + 11 → ~3 min  (verification + lessons + summary)
Slide 9 (Layer 2 / Elle) is the headline — leave the most time for it

Each slide has three parts:

1. On screen — what the audience sees.
2. Visual — figure file under `../ppt_figures/`.
3. Script — exact words to read aloud.

Regenerate figures with `python3 ../scripts/generate_ppt_figures.py`.

---

## Slide 1 — Title

### On screen
Removing the Sister-Replica Assumption from Pesto
A heterogeneous-membership extension for cross-shard BFT SQL
Jiatong Li · CS 598 FTS · Spring 2026

### Visual
Title slide.

### Script
Hi everyone. We extended Pesto, a recent Byzantine-fault-tolerant SQL
database, to remove a structural assumption
its authors call the sister-replica assumption. I'll first define what
Pesto is and what that assumption means in concrete terms, then show what
we changed, and what we measured on a real eighteen-node CloudLab cluster.
27
---

## Slide 2 — What is Pesto?

### On screen
A SQL database where replicas may behave maliciously, not just crash
Data is split across shards (key ranges); each shard is replicated
Shard size: `n = 5f+1` replicas to tolerate `f` malicious ones
Single-shard txn: 1 round-trip on the fast path; falls back to a slower recovery if a replica misbehaves

### Visual
Figure file: `ppt_figures/fig_02_pesto_arch.png`

### Script
Quick definition of Pesto. Like any sharded database, Pesto splits its
tables across shards by key range.  To tolerate f byzantine replicas per shard,
Pesto needs five-f-plus-one nodes per shard. The reason it's five-f-plus-one and not the
textbook three-f-plus-one is that Pesto wants to commit in a single
round-trip on the happy path, and that requires larger quorums to
detect a lying replica without a second round. If a replica
misbehaves, the protocol falls back to a slower multi-round recovery.
39
---

## Slide 3a — Why Pesto Needs Cross-Shard Coordination

### On screen
Cross-shard nested query: the inner result determines which shards the outer touches
Example: `SELECT * FROM accounts WHERE owner_id IN (SELECT id FROM users WHERE region='US')`
The set of "outer" shards depends on the inner result `R`
BFT risk: different replicas may pick different downstream shard sets → snapshot diverges

### Visual
Figure file: `ppt_figures/fig_03a_nested_query.png`

### Script
Before I introduce the assumption, let me set up why it exists. Pesto
needs to coordinate cross-shard queries that nest — meaning the result
of an inner sub-query determines which shards the outer sub-query has
to touch. In this example, you first ask Shard A which user IDs match
some predicate, get back a result `R`, and then go to whichever
"accounts" shards hold rows for those IDs. The catch is that, in a
Byzantine setting, replicas in Shard A could disagree on `R` and pick
different downstream shard sets. Without some agreement mechanism,
the cross-shard snapshot diverges and the query fails to serialize.

---

## Slide 3b — The Sister-Replica Assumption (Pesto's Fix)

### On screen
Pesto §B.10 (paraphrased):
  "We assume each shard includes a replica operated by the same trust authority — every replica has a trusted counterpart in other shards."
Trust authority = an organization (bank, university) that owns one node + key
Sister = same authority's replica in another shard
Effect: cross-shard trust collapses to organization-level trust — replicas trust signatures from same-organization sisters without extra crypto, so cross-shard verification is implicit
Cost: every shard must include the same set of owners

### Visual
Figure file: `ppt_figures/fig_03b_sister_assumption.png`

### Script
Pesto's fix is the sister-replica assumption. A trust authority is one
organization — say, a bank or a university — that owns one node and
its key. The paper assumes every such authority has a replica in every
single shard. The diagram shows this — same colors in both shards,
dashed lines connecting each authority to its sister.

Why does this fix the inconsistent-shard-set problem? Because cross-shard
trust collapses to organization-level trust. When shard A's replica run
by organization X needs to coordinate with shard B, the matching X-owned
replica is right there in shard B — same owner, signatures verify
implicitly, no extra cryptographic infrastructure needed. Inside each
shard the replicas still run a Byzantine quorum to pin down the
official intermediate result, and sisters carry that result to the next
shard for free. The paper itself is brief here — it explicitly defers
"efficient, trust-free cross-shard execution" to future work.

The structural cost is that every shard must include the same set of
owners. Pesto's implementation also forces equal `n` and `f`, but
that's a code-level restriction layered on top — not a logical
consequence of the assumption itself.

---

## Slide 3c — What This Project Enables

### On screen
Heterogeneous shards: completely disjoint owners, different `n` and `f`
No sisters → can't use Pesto's mechanism
Replaced by:
  shard membership certificate (signed list of public keys per shard)
  snapshot certificate carrying `2f+1` replica signatures
Any foreign shard verifies the cert locally — no shared admin needed
Pesto explicitly leaves "efficient, trust-free cross-shard execution" as future work — that's the gap we filled

### Visual
Figure file: `ppt_figures/fig_03c_heterogeneous.png`

### Script
The configuration we want to support is on this slide — Shard A run by
six universities with one tolerated fault, Shard B run by eleven
federal agencies with two tolerated faults, no overlap in owners.
There are no sisters here, so Pesto's mechanism doesn't apply. Our
replacement is two pieces of crypto. Each shard publishes a signed
membership certificate listing its members and their public keys.
When one shard sends a snapshot to another, it attaches enough replica
signatures — two-f-plus-one of them — that the receiver can verify
the snapshot is real, even with no shared owner between the shards.
2.48
---

## Slide 4 — Testbed: 18 nodes on CloudLab Utah

### On screen
18 × `amd` nodes on CloudLab Utah (academic research cloud)
12 servers (2 shards × 6) + 6 clients, each running our patched Pesto binary
One-shot setup script: SSH plumbing + Ed25519 key distribution + binary verification
Orchestrator: parallel SSH launch, env-var driven (`BYZ_PER_SHARD`, `BYZ_CLIENT_COUNT`, `NUM_TABLES`, …), pulls back stats and Elle history files

### Visual
Figure file: `ppt_figures/fig_06_topology.png`

### Script (~45s)
The testbed is eighteen identical AMD nodes on CloudLab Utah. Twelve
are servers, six per shard; six are clients driving load. Plumbing SSH
and Ed25519 keys across eighteen nodes was the most tedious part of
the project — one setup script now handles it. A second orchestrator
script reads environment variables for the experiment configuration,
launches every server and client over SSH in parallel, and pulls back
the per-client stats and Elle history files.

---

## Slide 5 — Experiment 1+2: Honest Baseline & Byzantine Injection

### On screen
6 clients × 30 s × `rw-sql` benchmark, 2 ops/txn

| Run | What is byzantine | tx/s | Commit % | Fast % |
|-----|-------------------|-----:|---------:|-------:|
| Exp1 | none (baseline) | 33.9 | 68.9 % | 100 % |
| Run 8 | 1 omission replica/shard + 1 crashing client | 32.7 | 70.6 % | ~98 % |
| Exp2 | 1 crash replica/shard + 1 crashing client | 32.8 | 71.5 % | 99.9 % |

Both byzantine runs within 3 % of honest — protocol absorbs faults
Slight fast-path drop: slow path kicks in when a replica misbehaves

### Visual
Figure file: `ppt_figures/fig_08_throughput_compare.png`

### Script (~60s)
First two experiments. Honest baseline: every replica behaves correctly,
six clients, thirty seconds. Just over a thousand commits, thirty-four
transactions per second, every commit on the fast path. The remaining
abort rate is normal optimistic-concurrency contention, not bugs.

Then we inject byzantine faults — one bad replica per shard plus a
client that crashes mid-transaction. Two replica fault types: silent
omission and full crash. The protocol absorbs both within three percent
of baseline. The fast-path ratio drops slightly because for some
transactions the slower fall-back path takes over. Notice "didn't
reply" and "isn't there" produce nearly identical numbers — at the
protocol layer, lying-by-silence and dying look the same.

---

## Slide 6 — Experiment 3: Multi-Shard Probe — A Negative Finding

### On screen
We *did* try to drive cross-shard activity:

| Run | NUM_TABLES | Commits | Cross-shard txns |
|-----|-----------:|--------:|-----------------:|
| Exp3 | 2 | 1 706 | 0 |
| Exp3b | 4 | 1 712 | 0 |

0 cross-shard txns in 6 412 commits across all 5 runs
Why: `RWSQLPartitioner` routes by `EncodeTable(table_name) % nshards` — each table lives on exactly one shard, and rw-sql txns touch one table → never span shards
Implication: our SS-CERT verifier code is in place but never invoked at runtime
Need a TPC-C-style workload to drive cross-shard txns

### Visual
Figure file: `ppt_figures/fig_06_topology.png`

### Script (~60s)
Third experiment is an honest negative finding, and it's the answer to
the obvious question "did you actually test cross-shard?". We tried.
We varied the number of tables — two and four — hoping rw-sql would
naturally produce transactions touching multiple shards. Throughput
went up because more tables means less contention, but the cross-shard
transaction count stayed at zero across six thousand commits.

We chased this down to the rw-sql partitioner: it routes by table
name modulo shard count, not by key. Each transaction in this benchmark
touches one table, so it never spans shards by design. That means our
cross-shard certificate verifier code is in place — unit tests pass,
servers generate their certs at startup — but it's never invoked at
runtime. To actually exercise it end-to-end, we'd need a workload
like TPC-C, where transactions naturally span multiple warehouses.
That's the most important item in future work.

---

## Slide 7 — Experiment 6: Heterogeneous Membership

### On screen
Configuration the original Pesto code panics on at startup:
  Shard 0: n=6, f=1 → fast quorum = 5 votes
  Shard 1: n=11, f=2 → fast quorum = 9 votes
Result: 408 commits in 30 s, 100 % commit, 100 % fast-path, no panics
What it shows: the per-shard quorum machinery negotiates two different sizes correctly in the same run
Caveat: byzantine injection was off in this run — heterogeneous + byzantine combined was not tested (in limitations)

### Visual
Figure file: `ppt_figures/fig_09_heterogeneous.png`

### Script (~55s)
Heterogeneous experiment. Shard zero has six replicas tolerating one
fault, needing a five-vote quorum. Shard one has eleven replicas
tolerating two faults, needing a nine-vote quorum. The original Pesto
code uses one global quorum size — it would panic at startup on this
configuration. With our per-shard machinery, the same client correctly
negotiates five votes from shard zero and nine from shard one in the
same run. Four hundred commits, every one on the fast path, no
panics. To be honest, byzantine injection was off in this run — we
never combined heterogeneous and byzantine in one run, and that's
called out in limitations.

---

## Slide 8 — Lessons, Gaps & What's Next

### On screen
Real bugs we hit:
  integer overflow in benchmark values silently aborted every txn for one client
  zombie processes from previous runs panicked the server at startup
  each fix = push code + rebuild on 18 nodes

Honest gaps:
  cross-shard verifier code is in place but workload doesn't drive it (Slide 6)
  heterogeneous + byzantine: tested separately, not combined
  "bad client" so far means "crashes", not "lies"

What's next:
  port a TPC-C-style workload to actually drive cross-shard txns
  combine heterogeneous + byzantine in one run (half-day config change)
  add lying-client testing

### Visual
Figure file: `ppt_figures/fig_12_bug_timeline.png`

### Script (~50s)
A quick honesty slide. Real bugs along the way — an integer overflow
in the benchmark silently aborted every transaction on one client,
and zombie processes from prior runs panicked the server at startup.
Each fix meant a fresh deploy across eighteen nodes — real
distributed-systems plumbing.

Honest gaps and what's next: the cross-shard certificate verifier
is implemented but our workload doesn't drive it — porting a
TPC-C-style benchmark is the most important next step. Combining
heterogeneous and byzantine in one run is a half-day config change.
And modeling malicious clients that actually lie, not just crash,
is the next layer of fault injection. Thanks; happy to take questions.

---

## Appendix — Q&A Prep

What does "SOSP" stand for? — Symposium on Operating Systems Principles,
  ACM's top-tier OS / systems conference. Pronounced letter by letter,
  S-O-S-P.
What is the "fast path" / "happy path"? — Same thing: the optimistic
  one-round-trip commit when nothing goes wrong (every replica votes,
  votes agree, no contention). When that fails — silent replica, conflicting
  votes — the protocol falls back to a slower multi-round path.
What does the sister-replica assumption actually do for Pesto? — It's
  a simplifying assumption used only for coordinating cross-shard
  distributed queries (Appendix B.10). The hard case is nested cross-shard
  queries where inner sub-query results determine which shards the outer
  sub-query touches — Byzantine replicas operated by different authorities
  could pick inconsistent shard sets. Sisters dodge this by giving every
  authority a representative in every shard. Pesto explicitly leaves
  trust-free cross-shard execution as future work; that's the gap we close.
Why `5f+1` instead of the classic `3f+1`? — PBFT uses two rounds, so its
  quorum intersection only needs one honest replica. Pesto wants to commit
  in one round, which requires a stronger intersection — at least `2f+1`
  honest replicas. Solving the constraints gives `n ≥ 5f+1`. Trade-off:
  more replicas, fewer round-trips.
What about throughput? — Honest baseline ~33.9 tx/s on 18 nodes; byzantine
  fault-injected runs (omission and crash) within 3 % of baseline. We chose
  to focus the talk on correctness rather than performance.
Why CloudLab Utah? — That's the cluster the course's CloudLab project
  gave us; identical hardware otherwise.
What's a "trust authority" in concrete terms? — An organization (bank,
  university) that owns one server and one Ed25519 key pair. Sister-replica
  meant the same organization had to be present in every shard.
Did you compare to vanilla Pesto? — Not directly; the SOSP run used
  ~200 nodes and we have 18. Our numbers are within an order of magnitude
  when scaled by client count.
What architecture changes did this require? — 24 files, ~1.2 KLoC across
  4 commits: per-shard `n`/`f` parsing, every quorum function rewritten to
  take a shard argument, a new membership-certificate module, and a new
  protobuf message for snapshot certificates carrying `2f+1` replica
  signatures.
Why a custom verifier instead of the real Elle? — Our sandbox refused
  to download the third-party jar. The JSON format is already compatible,
  so swap is an hour of work.
What's the difference between the two verification layers? — Layer one
  reads protocol counters; it cannot see actual data values. Layer two
  reads the values and looks for impossible read/write orderings. Layer
  one catches gross implementation bugs; layer two is the real safety check.
Did the data-layer check find any safety bugs in Pesto? — No, both
  honest and byzantine pass cleanly. That's the expected result; Pesto's
  paper proves safety. The value is now we have an automated regression
  test for future changes.
What was the hardest bug? — A hidden integer overflow that silently
  aborted every transaction on most clients. Took two rebuild-and-rerun
  cycles to spot, because the protocol layer reported "everything fine".
What's "equivocation"? — A Byzantine actor sending two contradictory
  messages to two different recipients, e.g. a leader telling shard A
  "T committed" and shard B "T aborted". Detecting it requires that any
  two quorums share enough honest witnesses to spot the contradiction —
  this is exactly why Pesto's quorum is `4f+1` rather than `2f+1`.
