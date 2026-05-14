# P1 — TPC-C cross-shard Elle (Adya / serializability) check

**Date:** 2026-05-12
**Code:** `cross-shard-membership` @ `b77ed899` (NewOrder Elle hooks + RAII guard)
**Tool:** `mini_elle.py` (G1a + G2) + ligurio/elle-cli 0.1.9 (list-append + serializable + strict-serializable)

## What this closes

L3 = "the committed history is serializable, no Adya G0/G1/G2 cycle."
Before P1, every Elle-validated history was rw-sql with **0 cross-shard
commits**. Cross-shard data layer was never inspected. P1 wires Elle
hooks into TPC-C `SQLNewOrder::Execute` and runs real Elle on the
captured cross-shard committed history.

## Modeling choice

TPC-C NewOrder maps to Elle **list-append** as: each NewOrder
`:append`s a globally-unique txn-value to per-warehouse keys
`w-<wid>` for every warehouse it touches (home + remote supply
warehouses for cross-warehouse line items). If two warehouses ever
disagreed on the order of cross-shard txns (e.g. W3 sees `[t1, t2]`
but W7 sees `[t2, t1]`), real Elle would flag a G2 cycle.

The 1% remote-supply line item logic from TPC-C spec means roughly
~5% of NewOrders span 2 warehouses (ol_cnt 5–15 × 1% per item).

## Two runs, both valid

| Run | Mode | Commits | Cross-shard (client) | L2 audit | mini_elle | Real Elle (list-append + serializable + strict-serializable) |
|-----|------|--------:|-----------------:|---------:|-----------|---------|
| `20260512T051713Z` | honest | 4 796 | 212 | **221 OK** / 0 violations | PASS | **valid? true** |
| `20260512T052106Z` | 1 byz/shard (omission) | 1 083 | 41 | **39 OK** / 0 violations | PASS | **valid? true** |

## What this proves

- **Cross-shard committed histories are serializable** (real Elle gold
  standard, list-append model, 1 642 + ~600 OK ops).
- Holds **under byzantine fault** at f=1 saturation per shard.
- **L1 + L2 + L3 all green simultaneously** on the SAME runs (this is
  the first time these aligned — previously L3 only had data on
  single-shard rw-sql and L1+L2 only had data on TPC-C without Elle).

## What this still doesn't prove

- Only NewOrder is instrumented. Payment / Delivery / OrderStatus / 
  StockLevel are silent in the Elle history. They commit (we count them
  in `total_commit_honest`) but their order doesn't enter the cycle
  graph. A real cycle through Payment ↔ NewOrder wouldn't be caught.
  Future hardening: instrument the other 4 txn classes the same way.
- The append-model abstracts away TPC-C's actual SQL (D_NEXT_O_ID
  increment, S_QUANTITY decrement). A bug that swaps two stocks
  invisibly to the warehouse-touched set wouldn't be caught either.
  Real defense-in-depth would also dump the SQL read/write set per
  txn into a separate rw-register history.

## Bug taxonomy that got us here

| Iter | Symptom | Root cause | Fix commit |
|------|---------|-----------|-----------|
| 1 | Real Elle: `:double-invoke` for process N | Multi-threaded benchmark sharing `FLAGS_client_id` as process | thread-local cached id (`fc64ffda`) |
| 2 | Still `:double-invoke` after thread-local | `hash<thread::id> & 0xFF` collisions among 8 worker threads | atomic counter (`184ff5a8`) |
| 3 | Still `:double-invoke` for one thread | Execute() returned/threw without emitting `:ok/:fail` (3 invokes for 1 ok) | RAII `EllGuard` emits `:info` on unresolved exit (`b77ed899`) |
| 4 | After RAII | **valid? true** under serializable + strict-serializable, both honest and byz | — |

## Reproduction

```bash
# honest
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=0 BYZ_CLIENT_COUNT=0 \
  DURATION=30 bash run_byzantine_experiment.sh
# byz
BENCHMARK=tpcc-sql WAREHOUSES=10 BYZ_PER_SHARD=1 BYZ_CLIENT_COUNT=0 \
  BYZ_REPLICA_MODE=inconsistency DURATION=30 \
  bash run_byzantine_experiment.sh

# verify, all three layers
LATEST=$(ls -td pesto-results/2026* | head -1)
cat $LATEST/elle/client-*.jsonl > $LATEST/elle/merged.jsonl
python3 scripts/l2_audit.py $LATEST          # L2
python3 scripts/mini_elle.py $LATEST/elle/merged.jsonl   # L3 partial
HOST=$(awk 'NF>=2 && $1=="ssh" {print $2; exit}' lab_ssh.txt)
scp $LATEST/elle/merged.jsonl $HOST:/tmp/m.jsonl
ssh $HOST 'python3 -c "import json; \
    arr=[json.loads(l) for l in open(\"/tmp/m.jsonl\") if l.strip()]; \
    json.dump(arr, open(\"/tmp/m.json\",\"w\"))"'
ssh $HOST 'java -jar /usr/local/bin/elle-cli.jar \
    --model list-append \
    --consistency-models serializable,strict-serializable \
    /tmp/m.json'
```
