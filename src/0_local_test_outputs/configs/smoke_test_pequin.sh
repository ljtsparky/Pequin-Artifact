#!/usr/bin/env bash
#
# Single-node smoke test for Pesto with our cross-shard membership extension.
#
# Spawns 6 replicas of one shard on localhost:8000-8005 (f=1, BFT default),
# runs N+1 benchmark clients for D seconds, then tears everything down.
#
# What this validates:
#   1. Server + benchmark binaries load & link without missing symbols
#   2. The full protocol path (Phase1, Phase2, Writeback) actually runs
#   3. Our cross-shard code does NOT regress the homogeneous single-shard case
#      (this is the T1 mini regression test from the eval doc)
#
# Run from anywhere on a CloudLab node:
#   bash /opt/Pequin-Artifact/src/0_local_test_outputs/configs/smoke_test_pequin.sh
#
# Optional flags:
#   -d <secs>   experiment duration  (default 10)
#   -c <n>      extra concurrent clients beyond client-0  (default 0, total = 1)
#   -k <n>      ops per txn  (default 2)
#   -n <n>      num keys in workload  (default 1)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUT_DIR="${SRC_DIR}/0_local_test_outputs/smoke_run"
CONFIG="${SCRIPT_DIR}/shard-r6.config"

DURATION=10
CLIENTS=0
KEYS=2
NUM_KEYS=1

while getopts d:c:k:n: opt; do
  case $opt in
    d) DURATION=$OPTARG ;;
    c) CLIENTS=$OPTARG ;;
    k) KEYS=$OPTARG ;;
    n) NUM_KEYS=$OPTARG ;;
    *) echo "Usage: $0 [-d secs] [-c clients] [-k ops] [-n keys]" >&2; exit 1 ;;
  esac
done

cd "$SRC_DIR"

# Clean up any stale processes from previous runs
for port in 8000 8001 8002 8003 8004 8005; do
  pids=$(lsof -ti:"$port" 2>/dev/null || true)
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
done
killall -q server 2>/dev/null || true
killall -q benchmark 2>/dev/null || true

# Make sure keys exist
if [ ! -d "${SRC_DIR}/keys" ] || [ -z "$(ls -A "${SRC_DIR}/keys" 2>/dev/null)" ]; then
  echo "Generating Ed25519 keys (one-time, ~30s)..."
  cd "$SRC_DIR" && ./keygen.sh
fi

mkdir -p "$OUT_DIR"
rm -f "${OUT_DIR}"/server-*.log "${OUT_DIR}"/client-*.log "${OUT_DIR}"/stats-*.json

cd "$SRC_DIR"

echo "=== Spawning 6 replicas on localhost:8000-8005 (protocol=pequin, f=1) ==="
for idx in 0 1 2 3 4 5; do
  store/server \
    --config_path "$CONFIG" \
    --group_idx 0 --num_groups 1 --num_shards 1 \
    --replica_idx "$idx" \
    --protocol pequin \
    --num_keys "$NUM_KEYS" \
    --indicus_key_path "${SRC_DIR}/keys" \
    --debug_stats \
    > "${OUT_DIR}/server-${idx}.log" 2>&1 &
done

sleep 2  # let servers come up

echo "=== Running $((CLIENTS+1)) client(s) for ${DURATION}s ==="

for i in $(seq 1 $CLIENTS); do
  store/benchmark/async/benchmark \
    --config_path "$CONFIG" \
    --num_groups 1 --num_shards 1 \
    --protocol_mode pequin \
    --num_keys "$NUM_KEYS" \
    --benchmark rw --num_ops_txn "$KEYS" \
    --exp_duration "$DURATION" \
    --client_id "$i" --warmup_secs 0 --cooldown_secs 0 \
    --key_selector zipf --zipf_coefficient 0.0 \
    --indicus_key_path "${SRC_DIR}/keys" \
    > "${OUT_DIR}/client-${i}.log" 2>&1 &
done

# Foreground client #0 — its exit blocks until duration elapses
store/benchmark/async/benchmark \
  --config_path "$CONFIG" \
  --num_groups 1 --num_shards 1 \
  --protocol_mode pequin \
  --num_keys "$NUM_KEYS" \
  --benchmark rw --num_ops_txn "$KEYS" \
  --exp_duration "$DURATION" \
  --client_id 0 --warmup_secs 0 --cooldown_secs 0 \
  --key_selector zipf --zipf_coefficient 0.0 \
  --stats_file "${OUT_DIR}/stats-0.json" \
  --indicus_key_path "${SRC_DIR}/keys" \
  > "${OUT_DIR}/client-0.log" 2>&1 || true

# Tear down
killall -q server 2>/dev/null || true
killall -q benchmark 2>/dev/null || true
sleep 1

echo
echo "=== Result ==="
echo "  Logs in: ${OUT_DIR}"
echo "  Server logs: server-{0..5}.log"
echo "  Client logs: client-0.log (+ client-{1..N}.log if -c > 0)"

if [ -f "${OUT_DIR}/stats-0.json" ]; then
  python3 - <<PYEOF
import json, sys
with open("${OUT_DIR}/stats-0.json") as f:
    s = json.load(f)
def find(d, k):
    if isinstance(d, dict):
        if k in d: return d[k]
        for v in d.values():
            r = find(v, k)
            if r is not None: return r
    return None
tput = find(s, 'tput')
n_committed = find(s, 'committed') or find(s, 'committed_total') or find(s, 'num_committed')
print(f"  Throughput field: {tput}")
print(f"  Committed txns:   {n_committed}")
if (isinstance(tput, dict) and tput.get('mean', 0) > 0) or (isinstance(tput, (int, float)) and tput > 0):
    print("  PASS  (real throughput recorded)")
    sys.exit(0)
elif n_committed and n_committed > 0:
    print("  PASS  (txns committed even if tput field empty)")
    sys.exit(0)
else:
    print("  WARN  no throughput / no committed txns — inspect server-*.log")
    sys.exit(1)
PYEOF
else
  echo "  FAIL: stats-0.json missing — check client-0.log:"
  echo "  --- last 20 lines of client-0.log ---"
  tail -20 "${OUT_DIR}/client-0.log" 2>/dev/null || echo "    (no log file)"
  echo "  --- last 20 lines of server-0.log ---"
  tail -20 "${OUT_DIR}/server-0.log" 2>/dev/null || echo "    (no log file)"
  exit 1
fi
