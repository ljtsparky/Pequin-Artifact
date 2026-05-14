# Pequin (Pesto Prototype) Codebase Overview

This document summarizes the structure and purpose of each directory and key file in the
Pequin-Artifact repository, with special attention to the areas relevant to our project:
**removing the sister-replica assumption for cross-shard coordination**.

---

## 1. Top-Level Directory Structure

```
Pequin-Artifact/
├── src/                        # All source code (C++, protobuf, scripts)
├── experiment-configs/         # JSON configs for running experiments
├── experiment-scripts/         # Python orchestration for CloudLab experiments
├── sample-output/              # Example benchmark result outputs
├── helper-scripts/             # Misc helper scripts
├── testing/                    # Developer test configs and scripts
├── setup/                      # Setup-related files
├── pg_setup/                   # PostgreSQL baseline setup
├── paper_108.pdf               # Pesto paper (SOSP'25)
├── Installation.md             # Build instructions
├── CloudlabSetup.md            # CloudLab cluster setup guide
├── RunningExperiments.md       # How to run experiments
├── Dockerfile                  # Docker build support
├── install_dependencies.sh     # Dependency installation script
└── README.md                   # Main documentation
```

---

## 2. `src/` -- Main Source Tree

### 2.1 `src/store/` -- Database Store Implementations

This is the heart of the codebase. Each subdirectory implements a different database system
or protocol variant.

#### 2.1.1 `src/store/pequinstore/` -- **Pesto (PRIMARY TARGET)**

The Pesto prototype itself. This is where the majority of our modifications will occur.

| File | Purpose | Relevance to Our Project |
|------|---------|--------------------------|
| `client.cc/h` (~3000 lines) | Client-side transaction orchestration: BEGIN, GET, PUT, COMMIT. Manages read/write buffering, drives the 2PC protocol, collects quorum votes. | **HIGH** -- Cross-shard query coordination originates here. The client acts as coordinator, collecting SS-VOTEs and assembling SS-PROPs across shards. We need to add cross-shard SS-CERT forwarding and verification logic here. |
| `server.cc/h` (~3500 lines) | Server-side replica logic: handles Phase1/Phase2 messages, runs concurrency control, executes queries, manages writeback. | **HIGH** -- Replicas currently trust messages from "sister replicas" in other shards. We need to add foreign SS-CERT verification using membership certificates. |
| `shardclient.cc/h` | Per-shard client stub. Handles communication with a single shard's replicas: sends Phase1/Phase2 requests, aggregates per-shard votes. | **HIGH** -- Cross-shard message routing passes through here. Needs to handle new cross-shard verification messages. |
| `common.cc/h` (43KB/92KB) | Shared data structures, cryptographic operations (signing, verification), async signature infrastructure. | **HIGH** -- New certificate types (Membership Certificates, extended SS-CERTs) and their verification logic will be added here. |
| `concurrencycontrol.cc` (~100KB) | MVTSO concurrency control. Implements SemanticCC (Algorithm 1 in the paper): conflict detection using Active Read Sets, predicate-based checks, dependency tracking. | **MEDIUM** -- CC logic is shard-local, but cross-shard snapshot consistency affects what timestamps are valid for CC checks. |
| `snapshot_mgr.cc` (~30KB) | Snapshot management: compression/decompression of transaction ID sets using VP4 and Frame-of-Reference encoding, local and merged snapshot coordination. | **HIGH** -- Snapshot synchronization is currently intra-shard. For cross-shard queries, we need to coordinate snapshots across shards with independent membership. |
| `querysync-client.cc` (~84KB) | Client-side query synchronization: query caching, snapshot proposal assembly (SS-PROP from SS-VOTEs), retry logic. | **HIGH** -- This is where SS-PROPs are assembled. For cross-shard queries, we need to coordinate proposals across multiple shards and forward SS-CERTs. |
| `querysync-server.cc` (~92KB) | Server-side query handling: processes SS-PROPs, materializes snapshots, synchronizes missing transactions between replicas. | **HIGH** -- Needs to handle foreign shard's SS-CERTs and verify them against membership certificates. |
| `querysync-servertools.cc` (~71KB) | Query execution utilities: table version tracking, snapshot materialization helpers. | MEDIUM |
| `sql_interpreter.cc/h` | SQL parsing and execution: column retrieval, query result building. | LOW -- SQL layer is unchanged. |
| `server_fallback.cc` | Cooperative fallback recovery protocol (from Basil). Allows any client to recover incomplete transactions. | LOW |
| `servertools.cc` (~92KB) | Server utility functions for message handling and state management. | MEDIUM |
| `clienttools.cc/h` | Client utility functions. | MEDIUM |
| `checkpointing.cc` | Checkpoint management (minimal). | LOW |
| `store.cc/h` | Store factory and initialization. | LOW |

**Cryptographic Components in pequinstore/:**

| File | Purpose |
|------|---------|
| `phase1validator.cc/h` | Validates Phase1 concurrency control results. |
| `basicverifier.cc/h` | Basic signature verification. |
| `localbatchsigner.cc/h` | Per-replica batch signature aggregation. |
| `localbatchverifier.cc/h` | Verification of local batch signatures. |
| `sharedbatchsigner.cc/h` | Cross-replica batch signature coordination. |
| `sharedbatchverifier.cc/h` | Verification of shared batch signatures. |
| `batchsigner.h` / `verifier.h` | Interfaces for batch signing and verification. |

**Database Backend Interface:**

| File | Purpose |
|------|---------|
| `table_store_interface.h` | Abstract interface for backend DB operations. |
| `table_store_interface_peloton.cc/h` | Peloton (full SQL DB) backend. Used in production runs. |
| `table_store_interface_toy.cc/h` | Simple in-memory backend for testing. |

**Protocol Buffer Definitions (CRITICAL):**

| File | Key Messages | Relevance |
|------|-------------|-----------|
| `pequin-proto.proto` (14KB) | `Transaction`, `Phase1`/`Phase2`, `CommittedProof`/`AbortedProof`, `Writeback`, `Fallback`, `Dependency`, `GroupedSignatures`, `V-CERT` | **HIGH** -- `GroupedSignatures` maps group_id to signatures (cross-shard proof). `Transaction.involved_groups` tracks which shards a txn touches. We need to add Membership Certificate and extended SS-CERT messages. |
| `query-proto.proto` (12KB) | `LocalSnapshot`, `MergedSnapshot`, `SyncClientProposal` (SS-PROP), `SupplyMissingTxns`, `RequestMissingTxns`, `QueryGroupMeta` | **HIGH** -- Snapshot protocol messages. Need new messages for cross-shard snapshot certificates and membership verification. |

#### 2.1.2 `src/store/indicusstore/` -- **Basil (Reference)**

The original Basil KV-store prototype. Pesto was built on top of this.

- Simpler than Pesto: no SQL interpreter, no snapshot manager, no query sync
- Same core structure: `client.cc`, `server.cc`, `shardclient.cc`, `common.cc`
- `indicus-proto.proto` -- similar to `pequin-proto.proto` but without query metadata
- Useful as reference for understanding the base commit protocol (2PC, V-CERTs, C-CERTs, A-CERTs)

#### 2.1.3 Other Store Implementations

| Directory | System | Purpose |
|-----------|--------|---------|
| `pelotonstore/` | Peloton (unreplicated SQL DB) | Baseline. Contains the Peloton DB engine under `peloton/` subdirectory. |
| `hotstuffstore/` | HotStuff SMR | Peloton-HS baseline. Contains `libhotstuff/` BFT consensus library. |
| `bftsmartstore/` | BFT-SMaRt SMR | Peloton-Smart baseline. Contains `library/` (Java BFT-SMaRt). |
| `postgresstore/` | PostgreSQL | Postgres baseline interface. |
| `cockroachdb/` | CockroachDB | CRDB baseline (deprecated on main, use `CRDB` branch). |
| `tapirstore/` | TAPIR | Crash fault tolerant baseline (from Basil comparison). |
| `strongstore/` | Strong consistency store | Another baseline. |
| `weakstore/` | Weak consistency store | Another baseline. |
| `blackholestore/` | Black hole (no-op) | Testing/benchmarking skeleton. |
| `augustusstore/` | Augustus | Experimental variant. |
| `pbftstore/` | PBFT | PBFT baseline. |
| `pg_SMRstore/` | PostgreSQL + SMR | Postgres layered on SMR. |

#### 2.1.4 `src/store/common/` -- Shared Infrastructure

| Component | Files | Purpose |
|-----------|-------|---------|
| **Frontend** | `frontend/client.h`, `frontend/txnclient.h`, `frontend/sync_client.cc` | Abstract client interfaces, synchronous/async transaction adapters. |
| **Backend** | `backend/kvstore.h`, `backend/txnstore.h`, `backend/versionstore.h` | Key-value store, transactional store, multi-version store abstractions. |
| **Query Results** | `query_result/*.h/cc`, `query-result-proto.proto` | Generic query result representation, proto-based row/field serialization. |
| **Partitioning** | `partitioner.cc/h` | Data partitioning across shards, key-to-group/replica mapping. **Relevant**: currently assumes static, identical membership. |
| **Timestamps** | `timestamp.cc/h`, `truetime.cc/h` | Logical timestamp representation, TrueTime for hybrid logical clocks. |
| **Transactions** | `transaction.cc/h` | Transaction abstraction (read/write sets). |
| **Common Proto** | `common-proto.proto` | Shared message types: `TimestampMessage`, `ReadMessage`, `WriteMessage`, `RowUpdates`, `TableWrite`. |
| **Statistics** | `stats.cc/h` | Performance metrics collection. |
| **Utilities** | `table_kv_encoder.cc/h`, `pinginitiator.h` | Key encoding/decoding, health checking. |

#### 2.1.5 `src/store/benchmark/` -- Benchmarks

Located under `benchmark/async/sql/`:
- **tpcc/** -- TPC-C (20 warehouses, high contention, point-read heavy)
- **auctionmark/** -- AuctionMark (range queries, joins, low contention)
- **seats/** -- Seats (airline booking, range queries, low contention)

Also: `rw/` (read-write microbenchmarks), `smallbank/`, `retwis/`, `tpcc/` (KV version), `toy/`.

#### 2.1.6 `src/store/tools/`

Utility tools for the store layer.

### 2.2 `src/lib/` -- Libraries (Networking, Crypto, Compression)

| Component | Files | Purpose |
|-----------|-------|---------|
| **Cryptography** | `crypto.cc/h` | Ed25519 signatures, HMAC-SHA256, encryption. **Relevant**: all cross-shard certificate verification uses this. |
| **Key Management** | `keymanager.cc/h` | Public/private key loading and management. **Relevant**: needs extension for per-shard membership keys. |
| **Batch Signatures** | `batched_sigs.cc/h` | Efficient batch signature aggregation/verification. |
| **Hashing** | `hash.h`, `blake3.h` | BLAKE3 hash functions. |
| **Networking** | `repltransport.cc`, `configuration.cc/h` | Transport abstraction, replica configuration parsing. **Relevant**: `configuration` defines shard membership statically. |
| **Messages** | `message.cc/h` | Message serialization/deserialization. |
| **Compression** | `compression/` | VP4 and Frame-of-Reference integer compression (used for snapshot compression). |
| **Concurrency** | `concurrentqueue/` | Lock-free concurrent queue library (moodycamel). |
| **Serialization** | `cereal/` | Header-only serialization library. |

### 2.3 `src/replication/` -- Replication Protocols

| Directory | Purpose |
|-----------|---------|
| `common/` | Shared replication abstractions (replica, client interfaces). |
| `ir/` | IR (Indulgent Replication) -- the underlying consensus used by Basil/Pesto. Tolerates inconsistent replicas, uses client-driven coordination. |
| `vr/` | Viewstamped Replication -- classical view-based protocol. |

### 2.4 Other `src/` Directories

| Directory | Purpose |
|-----------|---------|
| `lockserver/` | Distributed lock server. |
| `timeserver/` | Timestamp server for ordering. |
| `create_keys/` | Key generation utilities for Ed25519 keys. |
| `ycsb-t/` | YCSB benchmark harness. |
| `scripts/` | Helper scripts for data generation, Postgres setup, HotStuff/BFT-Smart configuration. |
| `Makefile` | Build system. Compiles all protobuf, C++17, links OpenSSL, libsodium, boost, libevent, Postgres libraries. |

---

## 3. `experiment-configs/` -- Experiment Configurations

JSON config files organized by system:

```
experiment-configs/
├── Pesto/
│   ├── 1-Workloads/          # TPC-C, AuctionMark, Seats
│   └── 2-Microbenchmarks/    # YCSB-based microbenchmarks
├── Basil/
│   ├── 1-Workloads/
│   ├── 2-Client-Failures/
│   └── ...
├── Peloton/                  # Unreplicated Peloton baseline
├── Postgres/                 # Postgres baseline
└── Cockroach-Deprecated/     # CRDB (use CRDB branch)
```

Key config parameters:
- `replication_protocol`: "pequin" for Pesto
- `num_shards`, `num_groups`: shard/group count
- `benchmark_name`: "tpcc-sql", "auctionmark-sql", "seats-sql"
- `server_regions`, `client_total`: deployment topology

## 4. `experiment-scripts/` -- Experiment Orchestration

- `run_experiment.py` -- Runs a single experiment from a JSON config
- `run_multiple_experiments.py` -- Batch runner for parameter sweeps
- `regenerate_plots.py` -- Post-processing and plotting
- `utils/` -- Experiment helper utilities

---

## 5. Key Concepts and Data Flow

### 5.1 Transaction Lifecycle (Single Shard)

```
Client                          Replicas (5f+1)
  |                                  |
  |--- BEGIN (assign ts_T) --------->|
  |--- GET/PUT (buffered) --------->|
  |                                  |
  |--- COMMIT (Phase1: Prepare) --->|  Replicas run SemanticCC check
  |<-- Phase1 Reply (Vote) ---------|  (Algorithm 1 in paper)
  |                                  |
  |--- Phase2 (Decision) ---------->|  (only if slow path)
  |<-- Phase2 Reply ----------------|
  |                                  |
  |--- Writeback (async) ---------->|  Replicas apply writes
```

### 5.2 Range Read / Query Lifecycle

```
Client                          Replicas (3f+1 or more)
  |                                  |
  |--- RANGE-READ (Q, ts_T) ------->|
  |<-- Q-RES, Q-READ, SS-VOTE ------|  (from each replica)
  |                                  |
  |  [Try Eager Path: f+1 matching results?]
  |  [If yes: done. If no: Snapshot Path]
  |                                  |
  |--- SS-PROP (merged snapshot) --->|  (propose common snapshot)
  |<-- Execute on snapshot ----------|  (replicas sync missing txns)
  |<-- Q-RES, Q-READ, Q-DEP --------|
  |                                  |
  |  [Collect f+1 matching results]
```

### 5.3 Cross-Shard Transaction Commit (Current Design)

```
Client                    Shard S1            Shard S2
  |                          |                    |
  |--- Phase1 (T) --------->|                    |
  |--- Phase1 (T) ------------------------------>|
  |<-- V-CERT_S1 ----------|                    |
  |<-- V-CERT_S2 --------------------------------|
  |                          |                    |
  |  [All shards vote commit? => C-CERT]
  |  [Any shard votes abort?  => A-CERT]
  |                          |                    |
  |--- Writeback (C-CERT) ->|                    |
  |--- Writeback (C-CERT) ------------------------>|
```

### 5.4 Cross-Shard Query (Current: Sister Replica Assumption)

From Pesto paper Appendix B.10:

> "For simplicity, we assume each shard includes a replica operated by the same trust
> authority (i.e., every replica has a trusted counterpart in other shards)."

**Current design**: Each authority runs replicas in ALL shards. Cross-shard coordination
exploits this: replicas in different shards belonging to the same authority can trust each
other without cryptographic proof.

**Our project**: Remove this assumption. Allow shards to have completely independent
membership. Introduce:
1. **Membership Certificates** -- each shard publishes signed list of its replicas
2. **Cross-Shard SS-CERTs** -- snapshot certificates verifiable by foreign shards
3. **Client as Coordinator** -- client collects and forwards SS-CERTs between shards

---

## 6. Files We Need to Modify (Priority Map)

### Priority 1: Protocol Messages (Define new certificate types)

- `src/store/pequinstore/pequin-proto.proto` -- Add MembershipCertificate, CrossShardSSCert messages
- `src/store/pequinstore/query-proto.proto` -- Add cross-shard snapshot coordination messages

### Priority 2: Client-Side Cross-Shard Coordination

- `src/store/pequinstore/client.cc/h` -- Implement cross-shard query protocol (flat + nested)
- `src/store/pequinstore/shardclient.cc/h` -- Route cross-shard verification messages
- `src/store/pequinstore/querysync-client.cc` -- Coordinate snapshot proposals across shards with independent membership

### Priority 3: Server-Side Verification

- `src/store/pequinstore/server.cc/h` -- Verify foreign SS-CERTs against membership certificates
- `src/store/pequinstore/querysync-server.cc` -- Handle cross-shard snapshot materialization
- `src/store/pequinstore/common.cc/h` -- Add membership certificate verification functions

### Priority 4: Infrastructure

- `src/lib/configuration.cc/h` -- Support per-shard independent membership configuration
- `src/lib/keymanager.cc/h` -- Manage per-shard public keys for membership verification
- `src/lib/crypto.cc/h` -- Any new crypto operations needed for certificates
- `src/store/common/partitioner.cc/h` -- Handle heterogeneous shard membership in partitioning

### Priority 5: Testing and Evaluation

- `experiment-configs/Pesto/` -- Add configs for heterogeneous shard experiments
- `src/store/benchmark/` -- Modify benchmarks to test cross-shard scenarios
- `testing/` -- Add unit tests for new certificate verification

---

## 7. Relationship to Pesto Paper Sections

| Paper Section | Code Location | Description |
|---------------|--------------|-------------|
| Section 5.1 (Data Structures) | `pequin-proto.proto`, `transaction.h` | Transactions, versions, timestamps |
| Section 5.4 (Point Read) | `client.cc` (GET path) | Single-row reads via Basil's protocol |
| Section 5.5 (Range Read / Snapshot) | `querysync-client.cc`, `querysync-server.cc`, `snapshot_mgr.cc` | SS-VOTE, SS-PROP, snapshot sync |
| Section 6.1 (SemanticCC) | `concurrencycontrol.cc`, `concurrencycontrol_semantic.cc` | Algorithm 1, ARS, predicate checks |
| Section 6.2 (Commit / 2PC) | `client.cc` (commit path), `server.cc` (Phase1/Phase2 handlers) | V-CERT, C-CERT, A-CERT |
| Appendix B.10 (Distributed Queries) | `querysync-client.cc`, `shardclient.cc` | **Sister replica assumption -- OUR TARGET** |
| Appendix B.5.2 (Nested Queries) | `querysync-client.cc` | Sequential snapshot dependencies -- **OUR TARGET** |

---

## 8. Build and Run

```bash
# Install dependencies
cd Pequin-Artifact
./install_dependencies.sh

# Build
cd src
make all        # Builds everything
make indicus     # Builds just the Pesto/Basil binary

# Generate keys
cd create_keys
./keygen.sh

# Run local test (see testing/ directory for configs)
```

The main binary is `src/store/server` (the compiled replica server). Clients are benchmark-specific binaries under `src/store/benchmark/`.
