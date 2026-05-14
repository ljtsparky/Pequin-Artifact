#!/usr/bin/env bash
#
# run_byzantine_experiment.sh — orchestrate a 2-shard, byzantine-fault Pesto
# experiment across 18 CloudLab nodes from THIS VM.
#
# Reads node hostnames from lab_ssh.txt (same file as setup_18_nodes.sh) and
# does:
#
#   - Generates a shard.config listing all 12 server endpoints (2 shards × 6 replicas)
#   - Pushes shard.config to all 18 nodes
#   - Launches store/server on the 12 server nodes (with --simulate_inconsistency=true
#     on $BYZ_PER_SHARD selected replicas per shard)
#   - Launches benchmark client on the 6 client nodes (with byzantine
#     inject_failure_proportion on the LAST client)
#   - Waits for the experiment duration to elapse
#   - Tears down servers + clients
#   - Pulls stats files back to this VM under pesto-results/<timestamp>/
#
# Node assignment (line N of lab_ssh.txt → role):
#   line 1..6   = shard 0, replica 0..5    (server)
#   line 7..12  = shard 1, replica 0..5    (server)
#   line 13..17 = honest client 0..4
#   line 18     = byzantine client 5
#
# Usage:
#   bash /home/student/CS598FTS/run_byzantine_experiment.sh
#
# Env overrides:
#   DURATION       experiment seconds                   (default 30)
#   F_PER_SHARD    fault tolerance per shard            (default 1, Pesto-safe with n=6)
#   BYZ_PER_SHARD  byzantine replicas per shard         (default 1; >1 violates 5f+1)
#   NUM_KEYS       workload key count                   (default 1000)
#   NUM_OPS        ops per txn                          (default 2)
#   BENCHMARK      benchmark name                       (default rw)
#   PROTOCOL       protocol_mode (server -> --protocol) (default pequin)
#   PORT_BASE      first replica port                   (default 7000)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_SSH_FILE="${LAB_SSH_FILE:-${SCRIPT_DIR}/lab_ssh.txt}"

DURATION="${DURATION:-30}"
F_PER_SHARD="${F_PER_SHARD:-1}"
BYZ_PER_SHARD="${BYZ_PER_SHARD:-1}"
BYZ_CLIENT_COUNT="${BYZ_CLIENT_COUNT:-1}"   # how many of the LAST clients are byzantine
BYZ_REPLICA_MODE="${BYZ_REPLICA_MODE:-inconsistency}"  # 'inconsistency' (omission) or 'failure' (full crash)
NUM_KEYS="${NUM_KEYS:-1000}"
NUM_OPS="${NUM_OPS:-2}"
NUM_TABLES="${NUM_TABLES:-1}"     # 1 = single-shard by RWSQLPartitioner;
                                    # >=2 lets txns span shards (~50% cross-shard
                                    # at NUM_TABLES=2 with NUM_OPS=2)
BENCHMARK="${BENCHMARK:-rw-sql}"  # 'rw-sql' is the maintained workload (the
                                   # one Pesto's published experiments use).
                                   # 'tpcc-sql' uses TPC-C — produces real
                                   # cross-shard txns via WarehouseSQLPartitioner.
                                   # Auto-generates schema when --data_file_path
                                   # has filename "rw-sql.json" + --sql_bench=true.
                                   # 'rw' (legacy) and 'toy' both broken upstream.
WAREHOUSES="${WAREHOUSES:-10}"     # number of TPC-C warehouses (only used
                                   # when BENCHMARK=tpcc-sql)
TPCC_DATA_DIR="${TPCC_DATA_DIR:-/opt/pesto-tpcc-data}"  # baked into image
PROTOCOL="${PROTOCOL:-pequin}"
PORT_BASE="${PORT_BASE:-7000}"
# PEQUIN_EAGER=true (default) → query takes optimistic eager-exec path,
# HandleSync/SS-CERT machinery NEVER fires. Set false to force the
# slow-path sync protocol so SyncClientProposal actually crosses the wire.
PEQUIN_EAGER="${PEQUIN_EAGER:-true}"
# SCAN_AS_POINT=true (default for rw-sql) → range scans treated as point reads,
# bypassing the multi-shard sync entirely. Set false (rw-sql only) to send
# real range queries that DO go through SyncReplicas / HandleSync.
SCAN_AS_POINT="${SCAN_AS_POINT:-true}"
# T13 adversarial cert injection: { none | one_vote | wrong_sig | wrong_group }
INJECT_BAD_SS_CERT="${INJECT_BAD_SS_CERT:-none}"
# P3.4 v3-strict: send query to all replicas so we get >= 2f+1 v3 votes per
# query naturally. { query-quorum | query-pessimistic-bonus | query-all }
QUERY_MESSAGES="${QUERY_MESSAGES:-query-quorum}"

# ---------- benchmark-specific flag bundles ----------
# Build server- and client-side workload flags once, based on BENCHMARK.
case "$BENCHMARK" in
  rw-sql)
    SERVER_WORKLOAD_FLAGS="--data_file_path /tmp/rwsql/rw-sql.json --num_tables $NUM_TABLES --num_keys_per_table $NUM_KEYS --value_size -1"
    CLIENT_WORKLOAD_FLAGS="--data_file_path /tmp/rwsql/rw-sql.json --num_tables $NUM_TABLES --num_keys_per_table $NUM_KEYS --value_size -1 --max_range 100 --rw_read_only=false --fixed_range=true --scan_as_point=$SCAN_AS_POINT"
    CLIENT_WORKLOAD_FLAGS="$CLIENT_WORKLOAD_FLAGS --key_selector ${KEY_SELECTOR:-zipf} --zipf_coefficient ${ZIPF_COEF:-0.5} --num_ops_txn $NUM_OPS --num_keys $NUM_KEYS"
    SERVER_WORKLOAD_FLAGS="$SERVER_WORKLOAD_FLAGS --num_keys $NUM_KEYS"
    PRELOAD_HINT_DIR=""   # rw-sql autogens, no pre-staged data
    ;;
  tpcc-sql)
    # IMPORTANT: --partitioner=warehouse routes by warehouse_id at the key
    # level, so cross-warehouse line items naturally produce cross-shard txns.
    # Default partitioner hashes table_name → all txns land on one shard.
    SERVER_WORKLOAD_FLAGS="--data_file_path ${TPCC_DATA_DIR}/sql-tpcc-tables-schema.json --tpcc_num_warehouses=$WAREHOUSES --partitioner=warehouse"
    CLIENT_WORKLOAD_FLAGS="--data_file_path ${TPCC_DATA_DIR}/sql-tpcc-tables-schema.json --tpcc_num_warehouses=$WAREHOUSES --partitioner=warehouse"
    PRELOAD_HINT_DIR="${TPCC_DATA_DIR}"   # must be pre-loaded on every node (image bake step)
    ;;
  *)
    echo "ERROR: BENCHMARK=$BENCHMARK not supported. Use rw-sql or tpcc-sql." >&2
    exit 1
    ;;
esac

# Pesto requires n = 5f+1 per shard.
#   f=1 → n=6   (default; fits 12 disjoint hosts + 6 clients = 18)
#   f=2 → n=11  (only fits with SISTER_REPLICA=true: 11 hosts + 7 clients = 18)
# REPLICAS_PER_SHARD can be overridden via env; defaults derived from F_PER_SHARD.
REPLICAS_PER_SHARD="${REPLICAS_PER_SHARD:-$((5 * F_PER_SHARD + 1))}"
NUM_SHARDS="${NUM_SHARDS:-2}"
NUM_SERVERS=$((NUM_SHARDS * REPLICAS_PER_SHARD))
NUM_CLIENTS="${NUM_CLIENTS:-6}"

# Sanity check on byzantine count
if [ "$BYZ_PER_SHARD" -gt "$F_PER_SHARD" ]; then
  echo "WARN: BYZ_PER_SHARD ($BYZ_PER_SHARD) > F_PER_SHARD ($F_PER_SHARD)."
  echo "      This violates Pesto's safety bound (n = 5f+1). Continuing anyway"
  echo "      to OBSERVE behavior under byzantine over-budget — expect deadlock"
  echo "      or non-serializable commits."
  sleep 2
fi

# Output dir on THIS VM
TS=$(date -u +"%Y%m%dT%H%M%SZ")
OUT_DIR="${SCRIPT_DIR}/pesto-results/${TS}"
mkdir -p "$OUT_DIR/configs" "$OUT_DIR/logs" "$OUT_DIR/stats"
echo "Results will land in: $OUT_DIR"

# ---------- read targets ----------
mapfile -t TARGETS < <(awk 'NF>=2 && $1=="ssh" {print $2}' "$LAB_SSH_FILE")
NEED=$((NUM_SERVERS + 1))   # at least enough hosts for servers + 1 client
if [ "${#TARGETS[@]}" -lt "$NEED" ]; then
  echo "ERROR: $LAB_SSH_FILE has only ${#TARGETS[@]} hosts; need >= $NEED for current config." >&2
  exit 1
fi

# SISTER_REPLICA=true puts both groups on the SAME 6 hosts (sister-replica
# trust model, original Pesto's assumption). Group 0 uses ports 7000-7005,
# group 1 uses ports 8000-8005. Frees 6 hosts so we can give clients more
# room: clients run on nodes 7-18 (12 hosts), pick first NUM_CLIENTS.
SISTER_REPLICA="${SISTER_REPLICA:-false}"
if [ "$SISTER_REPLICA" = "true" ]; then
  # Build SERVERS = first 6 hosts repeated twice (12 server processes on 6 machines)
  SERVERS=("${TARGETS[@]:0:REPLICAS_PER_SHARD}" "${TARGETS[@]:0:REPLICAS_PER_SHARD}")
  # In sister-replica mode, hosts 6..17 (12 nodes) are free for clients.
  CLIENT_HOSTS=("${TARGETS[@]:REPLICAS_PER_SHARD}")
else
  SERVERS=("${TARGETS[@]:0:NUM_SERVERS}")
  # In heterogeneous mode, hosts 12..17 (6 nodes) are client nodes.
  CLIENT_HOSTS=("${TARGETS[@]:NUM_SERVERS}")
fi

# Build CLIENTS array by cycling through CLIENT_HOSTS. If NUM_CLIENTS exceeds
# the host slot count, each excess client lands on a hash-distributed host
# (multi-client-per-host). Each client process gets a unique client_id and
# stats path on the remote node, so collocation is safe.
CLIENTS=()
for ((__i=0; __i<NUM_CLIENTS; __i++)); do
  CLIENTS+=("${CLIENT_HOSTS[__i % ${#CLIENT_HOSTS[@]}]}")
done

echo
echo "Server replicas (group_idx, replica_idx → host):"
for i in "${!SERVERS[@]}"; do
  group=$(( i / REPLICAS_PER_SHARD ))
  rep=$(( i % REPLICAS_PER_SHARD ))
  printf "  shard %d / replica %d  →  %s\n" "$group" "$rep" "${SERVERS[$i]}"
done
echo
echo "Clients:"
for i in "${!CLIENTS[@]}"; do
  byz=""
  [ "$i" -eq $((NUM_CLIENTS-1)) ] && byz="  ⚠ BYZANTINE (inject_failure_proportion=0.2)"
  printf "  client %d  →  %s%s\n" "$i" "${CLIENTS[$i]}" "$byz"
done

# Which replicas are byzantine? Last $BYZ_PER_SHARD replicas in each shard.
is_byzantine_replica() {
  local rep=$1
  local first_byz=$(( REPLICAS_PER_SHARD - BYZ_PER_SHARD ))
  [ "$rep" -ge "$first_byz" ]
}

SSH_OPTS=(
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -o ConnectTimeout=10
)

# ---------- generate shard.config locally ----------
# Pesto config format:
#   f <fault tolerance>
#   group
#   replica <host>:<port>
#   ... (n times)
#   group
#   replica <host>:<port>
#   ... (n times)
SHARD_CONFIG="${OUT_DIR}/configs/shard.config"
{
  echo "f $F_PER_SHARD"
  for g in $(seq 0 $((NUM_SHARDS-1))); do
    echo "group"
    for r in $(seq 0 $((REPLICAS_PER_SHARD-1))); do
      idx=$(( g * REPLICAS_PER_SHARD + r ))
      host="${SERVERS[$idx]#*@}"   # strip "user@"
      # In sister-replica mode, group 0 uses 7000+r, group 1 uses 8000+r
      # so two server processes can coexist on the same host.
      if [ "$SISTER_REPLICA" = "true" ]; then
        port=$((PORT_BASE + g * 1000 + r))
      else
        port=$((PORT_BASE + r))
      fi
      printf "replica %s:%d\n" "$host" "$port"
    done
  done
} > "$SHARD_CONFIG"

echo
echo "Generated shard.config:"
cat "$SHARD_CONFIG"

# ---------- pre-cleanup: kill any stale server/benchmark from a prior run ----------
# Without this, a prior run that we had to kill -9 leaves zombies bound to port
# 7000..7005, and every fresh server PANICs at "Address already in use".
echo
echo "=== Pre-cleanup: killing stale server/benchmark on all 18 nodes ==="
for t in "${TARGETS[@]}"; do
  ssh "${SSH_OPTS[@]}" "$t" "killall -q -9 server 2>/dev/null; killall -q -9 benchmark 2>/dev/null; true" &
done
wait
# Give the kernel a moment to release the bound TCP ports
sleep 2
echo "  done"

# Push to every node
echo
echo "=== Pushing shard.config to all 18 nodes ==="
for t in "${TARGETS[@]}"; do
  printf "  -> %-40s " "${t#*@}"
  scp -q "${SSH_OPTS[@]}" "$SHARD_CONFIG" "$t:/tmp/shard.config" \
    && echo "ok" || echo "FAIL"
done

# ---------- launch servers ----------
echo
echo "=== Launching servers (12 replicas, 2 shards) ==="
for i in "${!SERVERS[@]}"; do
  group=$(( i / REPLICAS_PER_SHARD ))
  rep=$(( i % REPLICAS_PER_SHARD ))
  host="${SERVERS[$i]}"

  byz_flag=""
  if is_byzantine_replica "$rep"; then
    case "$BYZ_REPLICA_MODE" in
      inconsistency) byz_flag="--pequin_simulate_inconsistency=true" ;;
      failure)       byz_flag="--pequin_simulate_replica_failure=true" ;;
      drop_xshard)   byz_flag="--pequin_drop_cross_shard_writeback=true" ;;
      twin_sig)      byz_flag="--pequin_twin_replica=true" ;;
      *) echo "Unknown BYZ_REPLICA_MODE: $BYZ_REPLICA_MODE"; exit 1 ;;
    esac
    role_tag="BYZ"
  else
    role_tag="ok "
  fi

  log_remote="/tmp/pesto_server_g${group}_r${rep}.log"
  server_stats_remote="/tmp/pesto_server_stats_g${group}_r${rep}.json"
  # Important: SSH non-interactively does NOT source /etc/bash.bashrc, so we
  # must source setvars.sh ourselves to make libtbb.so.12 visible.
  # The "</dev/null" is critical: without it ssh hangs because the backgrounded
  # nohup process inherits the SSH stdin and ssh waits for it to close.
  # rw-sql autogenerates schema if filename=="rw-sql.json" + --sql_bench=true.
  # USE_ORIGIN=true switches to /opt/Pequin-Artifact-Origin/src/store/server
  # (the pre-extension Pesto binary) and skips our extension-only flags.
  USE_ORIGIN="${USE_ORIGIN:-false}"
  if [ "$USE_ORIGIN" = "true" ]; then
    BIN_DIR="/opt/Pequin-Artifact-Origin/src"
    # Origin binary doesn't know our byz flags or stats fields
    byz_flag=""
  else
    BIN_DIR="/opt/Pequin-Artifact/src"
  fi
  cmd="source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1; \
       export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:\$LD_LIBRARY_PATH; \
       mkdir -p /tmp/rwsql && \
       cd $BIN_DIR && \
       nohup ./store/server \
         --config_path /tmp/shard.config \
         --num_groups $NUM_SHARDS --num_shards $NUM_SHARDS \
         --group_idx $group --replica_idx $rep \
         --protocol $PROTOCOL \
         --indicus_key_path $BIN_DIR/keys \
         --sql_bench=true \
         $SERVER_WORKLOAD_FLAGS \
         --debug_stats \
         --stats_file=$server_stats_remote \
         --pequin_query_eager_exec=$PEQUIN_EAGER \
         --pequin_eager_plus_snapshot=$PEQUIN_EAGER \
         $byz_flag \
         > $log_remote 2>&1 </dev/null &"

  printf "  %s shard %d / replica %d  on %-30s ... " "$role_tag" "$group" "$rep" "${host#*@}"
  # -f forks ssh into background after auth, so we don't wait on the remote
  # session staying open while the server runs detached.
  ssh -f "${SSH_OPTS[@]}" "$host" "$cmd" \
    && echo "launched" \
    || echo "FAIL"
done

echo
echo "=== Waiting 5s for servers to bind ports ==="
sleep 5

# ---------- launch clients ----------
echo
echo "=== Launching $NUM_CLIENTS clients (last one byzantine) for ${DURATION}s ==="
CLIENT_PIDS=()
for i in "${!CLIENTS[@]}"; do
  host="${CLIENTS[$i]}"
  client_id=$i

  byz_flags=""
  # Last BYZ_CLIENT_COUNT clients are byzantine (0 = all honest baseline).
  if [ "$i" -ge $((NUM_CLIENTS - BYZ_CLIENT_COUNT)) ] && [ "$BYZ_CLIENT_COUNT" -gt 0 ]; then
    # NOTE: indicus_inject_failure_proportion is a uint64 percentage (0-100), not a fraction.
    byz_flags="--indicus_inject_failure_proportion=20 --indicus_inject_failure_freq=10 --indicus_inject_failure_type=client-crash"
    role_tag="BYZ"
  else
    role_tag="ok "
  fi

  log_remote="/tmp/pesto_client_${i}.log"
  stats_remote="/tmp/pesto_stats_${i}.json"
  elle_remote="/tmp/pesto_elle_${i}.jsonl"

  if [ "$USE_ORIGIN" = "true" ]; then
    CLIENT_BIN_DIR="/opt/Pequin-Artifact-Origin/src"
    # Origin lacks pequin_inject_bad_ss_cert and elle_history_path (our additions);
    # it DOES have pequin_query_messages (upstream Pesto flag)
    origin_skip_flag=""
    elle_flag=""
  else
    CLIENT_BIN_DIR="/opt/Pequin-Artifact/src"
    origin_skip_flag="--pequin_inject_bad_ss_cert=$INJECT_BAD_SS_CERT"
    elle_flag="--elle_history_path $elle_remote"
  fi
  # query_messages is upstream — pass to both
  origin_qm_flag="--pequin_query_messages=$QUERY_MESSAGES"
  cmd="source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1; \
       export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:\$LD_LIBRARY_PATH; \
       mkdir -p /tmp/rwsql && \
       cd $CLIENT_BIN_DIR && \
       ./store/benchmark/async/benchmark \
         --config_path /tmp/shard.config \
         --num_groups $NUM_SHARDS --num_shards $NUM_SHARDS \
         --protocol_mode $PROTOCOL \
         --benchmark $BENCHMARK \
         --exp_duration $DURATION \
         --client_id $client_id \
         --warmup_secs 5 --cooldown_secs 5 \
         --stats_file $stats_remote \
         $elle_flag \
         --indicus_key_path $CLIENT_BIN_DIR/keys \
         --sql_bench=true \
         $CLIENT_WORKLOAD_FLAGS \
         --pequin_query_eager_exec=$PEQUIN_EAGER \
         --pequin_eager_plus_snapshot=$PEQUIN_EAGER \
         $origin_skip_flag \
         $origin_qm_flag \
         --retry_aborted=true \
         --max_attempts=10 \
         $byz_flags \
         > $log_remote 2>&1"

  printf "  %s client %d  on %-30s ... " "$role_tag" "$i" "${host#*@}"
  ssh "${SSH_OPTS[@]}" "$host" "$cmd" \
    > "$OUT_DIR/logs/client-${i}-launch.log" 2>&1 &
  CLIENT_PIDS+=($!)
  echo "launched (pid $!)"
done

# Foreground: wait for all clients to finish
echo
echo "=== Waiting for clients to finish (~$((DURATION + 10))s) ==="
TOTAL=$(( DURATION + 30 ))
for elapsed in $(seq 1 "$TOTAL"); do
  sleep 1
  # Are any clients still running?
  alive=0
  for pid in "${CLIENT_PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null && alive=$((alive+1))
  done
  printf "\r  elapsed: %ds / %ds   clients alive: %d/%d   " "$elapsed" "$TOTAL" "$alive" "$NUM_CLIENTS"
  [ "$alive" -eq 0 ] && break
done
echo
# IMPORTANT: scp the stats files BEFORE killing anything.
# Pesto's benchmark.cc has a tport->Timer(exp_duration*1000-1000, FlushStats)
# that writes complete stats to disk at ~exp_duration-1s. After that the
# benchmark keeps running forever waiting for SIGTERM. If we then SIGTERM it,
# Cleanup() fires twice (once via signal handler, once via main's `Cleanup(0)`
# after tport->Run() returns) and the SECOND FlushStats writes "{}" because
# the client objects have already been deleted. So we MUST scp before killing.
echo
echo "=== Pulling stats + Elle history from each client (BEFORE kill, to dodge the double-Cleanup empty-overwrite bug) ==="
mkdir -p "$OUT_DIR/elle"
for i in "${!CLIENTS[@]}"; do
  host="${CLIENTS[$i]}"
  printf "  client %d stats ... " "$i"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_stats_${i}.json" "$OUT_DIR/stats/client-${i}.json" \
    && echo "ok" || echo "MISSING"
  printf "  client %d elle  ... " "$i"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_elle_${i}.jsonl" "$OUT_DIR/elle/client-${i}.jsonl" \
    && echo "ok" || echo "MISSING"
done

# Hard-kill any local ssh waiters that didn't exit (Pesto client sometimes
# holds the SSH stream open during cleanup, causing 'wait' to block forever).
for pid in "${CLIENT_PIDS[@]}"; do
  kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null
done
sleep 2
for pid in "${CLIENT_PIDS[@]}"; do
  kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
done

# ---------- tear down servers ----------
echo
echo "=== Killing remaining server/benchmark processes on all 18 nodes ==="
# SIGTERM (default for killall) triggers server's Cleanup() handler, which
# writes the stats file. Give it 3s to finish before pulling stats files.
for t in "${TARGETS[@]}"; do
  ssh "${SSH_OPTS[@]}" "$t" "killall -q server 2>/dev/null; killall -q benchmark 2>/dev/null; true" &
done
wait
sleep 3
echo "  done"

# ---------- collect logs (after kill, since logs keep growing till the kill) ----------
echo
echo "=== Pulling client + server logs back to $OUT_DIR ==="

# Client logs
for i in "${!CLIENTS[@]}"; do
  host="${CLIENTS[$i]}"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_client_${i}.log" "$OUT_DIR/logs/client-${i}.log" \
    2>/dev/null
done

# Server logs
for i in "${!SERVERS[@]}"; do
  group=$(( i / REPLICAS_PER_SHARD ))
  rep=$(( i % REPLICAS_PER_SHARD ))
  host="${SERVERS[$i]}"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_server_g${group}_r${rep}.log" \
    "$OUT_DIR/logs/server-g${group}-r${rep}.log" 2>/dev/null
done

# Server stats (membership_cert_loaded, ss_cert_*, handle_sync_total, etc.)
mkdir -p "$OUT_DIR/server_stats"
for i in "${!SERVERS[@]}"; do
  group=$(( i / REPLICAS_PER_SHARD ))
  rep=$(( i % REPLICAS_PER_SHARD ))
  host="${SERVERS[$i]}"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_server_stats_g${group}_r${rep}.json" \
    "$OUT_DIR/server_stats/server-g${group}-r${rep}.json" 2>/dev/null
done

# Save the run params alongside results (so we can reproduce)
cat > "$OUT_DIR/run_params.txt" <<EOF
TIMESTAMP=$TS
DURATION=$DURATION
F_PER_SHARD=$F_PER_SHARD
BYZ_PER_SHARD=$BYZ_PER_SHARD
NUM_KEYS=$NUM_KEYS
NUM_OPS=$NUM_OPS
BENCHMARK=$BENCHMARK
PROTOCOL=$PROTOCOL
NUM_SHARDS=$NUM_SHARDS
REPLICAS_PER_SHARD=$REPLICAS_PER_SHARD
NUM_CLIENTS=$NUM_CLIENTS
LAB_SSH_FILE=$LAB_SSH_FILE
NUM_TABLES=$NUM_TABLES
PEQUIN_EAGER=$PEQUIN_EAGER
SCAN_AS_POINT=$SCAN_AS_POINT
QUERY_MESSAGES=$QUERY_MESSAGES
BYZ_REPLICA_MODE=$BYZ_REPLICA_MODE
INJECT_BAD_SS_CERT=$INJECT_BAD_SS_CERT
SISTER_REPLICA=$SISTER_REPLICA
EOF

# ---------- summary ----------
echo
echo "================ Summary ================"
echo "  Output dir:    $OUT_DIR"
echo "  Stats files:   $(ls -1 "$OUT_DIR/stats/" 2>/dev/null | wc -l) / $NUM_CLIENTS"
echo "  Server logs:   $(ls -1 "$OUT_DIR/logs/server-"*.log 2>/dev/null | wc -l) / $NUM_SERVERS"
echo "  Client logs:   $(ls -1 "$OUT_DIR/logs/client-"*.log 2>/dev/null | wc -l) / $NUM_CLIENTS"

# Quick PASS/FAIL: any honest client recorded committed txns?
ok=0
for i in $(seq 0 $((NUM_CLIENTS-2))); do   # exclude byzantine (last) client
  f="$OUT_DIR/stats/client-${i}.json"
  [ ! -s "$f" ] && continue
  tput=$(python3 -c "
import json, sys
try: s=json.load(open('$f'))
except: sys.exit()
def find(d,k):
    if isinstance(d,dict):
        if k in d: return d[k]
        for v in d.values():
            r=find(v,k)
            if r is not None: return r
    return None
v=find(s,'tput')
if isinstance(v,dict): v=v.get('mean',0)
print(v or 0)
" 2>/dev/null)
  [ -n "$tput" ] && [ "$(python3 -c "print(float('$tput')>0)" 2>/dev/null)" = "True" ] \
    && ok=$((ok+1))
done

echo
if [ "$ok" -gt 0 ]; then
  echo "  RESULT: $ok honest clients recorded throughput > 0  ⇒  PASS"
  echo "  Inspect $OUT_DIR/stats/ for per-client tput / latency."
  exit 0
else
  echo "  RESULT: 0 honest clients with throughput > 0  ⇒  FAIL"
  echo "  Inspect $OUT_DIR/logs/ — likely server/client crash. tail -30 of each:"
  for f in "$OUT_DIR/logs/"*.log; do
    echo "  --- $(basename "$f") ---"
    tail -5 "$f"
  done
  exit 1
fi
