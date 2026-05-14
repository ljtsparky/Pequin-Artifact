#!/usr/bin/env bash
#
# run_heterogeneous_experiment.sh — Exp6: prove the heterogeneous
# membership config (per-shard n and f) actually boots and commits
# transactions end-to-end on the 18-node CloudLab.
#
# Layout (the project's whole point — different shards have different
# replica counts):
#   shard 0: n=6, f=1  (6 servers, hosts from lab_ssh.txt lines 1..6)
#   shard 1: n=11, f=2 (11 servers, hosts from lab_ssh.txt lines 7..17)
#   client : 1 (lab_ssh.txt line 18)
#
# This exercises the per-group quorum machinery: shard 0 uses
# 4f+1 = 5-msg quorums, shard 1 uses 4f+1 = 9-msg quorums. If the
# code paths still hard-code the global f instead of GroupF(group),
# shard 1 will never form a quorum and will hang.
#
# Env overrides:
#   DURATION    seconds (default 30)
#   BYZ_S0      byz replicas in shard 0 (default 0)
#   BYZ_S1      byz replicas in shard 1 (default 0)
#   NUM_TABLES  tables (default 1)
#   NUM_KEYS    keys per table (default 1000)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_SSH_FILE="${LAB_SSH_FILE:-${SCRIPT_DIR}/lab_ssh.txt}"

DURATION="${DURATION:-30}"
BYZ_S0="${BYZ_S0:-0}"
BYZ_S1="${BYZ_S1:-0}"
# inconsistency = silent omission, failure = process crash
BYZ_REPLICA_MODE="${BYZ_REPLICA_MODE:-inconsistency}"
NUM_TABLES="${NUM_TABLES:-1}"
NUM_KEYS="${NUM_KEYS:-1000}"
NUM_OPS="${NUM_OPS:-2}"
PROTOCOL="${PROTOCOL:-pequin}"
PORT_BASE="${PORT_BASE:-7000}"

S0_N=6
S0_F=1
S1_N=11
S1_F=2
NUM_SHARDS=2
NUM_SERVERS=$((S0_N + S1_N))   # 17
NUM_CLIENTS=1
NUM_NODES=$((NUM_SERVERS + NUM_CLIENTS))   # 18

TS=$(date -u +"%Y%m%dT%H%M%SZ")
OUT_DIR="${SCRIPT_DIR}/pesto-results/het-${TS}"
mkdir -p "$OUT_DIR/configs" "$OUT_DIR/logs" "$OUT_DIR/stats"
echo "Results will land in: $OUT_DIR"

mapfile -t TARGETS < <(awk 'NF>=2 && $1=="ssh" {print $2}' "$LAB_SSH_FILE")
if [ "${#TARGETS[@]}" -ne 18 ]; then
  echo "ERROR: $LAB_SSH_FILE must have 18 lines, got ${#TARGETS[@]}." >&2
  exit 1
fi

S0_HOSTS=("${TARGETS[@]:0:$S0_N}")
S1_HOSTS=("${TARGETS[@]:$S0_N:$S1_N}")
CLIENT_HOSTS=("${TARGETS[@]:$NUM_SERVERS:$NUM_CLIENTS}")

echo
echo "Shard 0 (n=$S0_N, f=$S0_F):"
for i in "${!S0_HOSTS[@]}"; do printf "  rep %d -> %s\n" "$i" "${S0_HOSTS[$i]}"; done
echo
echo "Shard 1 (n=$S1_N, f=$S1_F):"
for i in "${!S1_HOSTS[@]}"; do printf "  rep %d -> %s\n" "$i" "${S1_HOSTS[$i]}"; done
echo
echo "Client(s):"
for h in "${CLIENT_HOSTS[@]}"; do echo "  $h"; done

SSH_OPTS=( -o StrictHostKeyChecking=accept-new
           -o UserKnownHostsFile=/dev/null
           -o LogLevel=ERROR
           -o ConnectTimeout=10 )

# ---------- generate heterogeneous shard.config ----------
SHARD_CONFIG="${OUT_DIR}/configs/shard.config"
{
  echo "f $S0_F"   # legacy global f (used as fallback)
  echo "group"
  echo "group_f $S0_F"
  for i in "${!S0_HOSTS[@]}"; do
    h="${S0_HOSTS[$i]#*@}"
    printf "replica %s:%d\n" "$h" "$((PORT_BASE + i))"
  done
  echo "group"
  echo "group_f $S1_F"
  for i in "${!S1_HOSTS[@]}"; do
    h="${S1_HOSTS[$i]#*@}"
    printf "replica %s:%d\n" "$h" "$((PORT_BASE + i))"
  done
} > "$SHARD_CONFIG"

echo
echo "Generated heterogeneous shard.config:"
cat "$SHARD_CONFIG"

# ---------- pre-cleanup ----------
echo
echo "=== Pre-cleanup: killall stale on all $NUM_NODES nodes ==="
for t in "${TARGETS[@]:0:$NUM_NODES}"; do
  ssh "${SSH_OPTS[@]}" "$t" "killall -q -9 server 2>/dev/null; killall -q -9 benchmark 2>/dev/null; true" &
done
wait
sleep 2

# ---------- push config ----------
echo
echo "=== Pushing config ==="
for t in "${TARGETS[@]:0:$NUM_NODES}"; do
  printf "  -> %-40s " "${t#*@}"
  scp -q "${SSH_OPTS[@]}" "$SHARD_CONFIG" "$t:/tmp/shard.config" \
    && echo ok || echo FAIL
done

# ---------- launch servers ----------
launch_server() {
  local host=$1 group=$2 rep=$3 byz=$4
  local byz_flag=""
  if [ "$byz" = "1" ]; then
    case "$BYZ_REPLICA_MODE" in
      failure)        byz_flag="--pequin_simulate_failure=true" ;;
      inconsistency)  byz_flag="--pequin_simulate_inconsistency=true" ;;
      *)              echo "ERROR: unknown BYZ_REPLICA_MODE=$BYZ_REPLICA_MODE" >&2; exit 1 ;;
    esac
  fi
  local log_remote="/tmp/pesto_server_g${group}_r${rep}.log"
  local stats_remote="/tmp/pesto_server_stats_g${group}_r${rep}.json"
  local cmd="source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1; \
       export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:\$LD_LIBRARY_PATH; \
       mkdir -p /tmp/rwsql && \
       cd /opt/Pequin-Artifact/src && \
       nohup ./store/server \
         --config_path /tmp/shard.config \
         --num_groups $NUM_SHARDS --num_shards $NUM_SHARDS \
         --group_idx $group --replica_idx $rep \
         --protocol $PROTOCOL \
         --num_keys $NUM_KEYS \
         --indicus_key_path /opt/Pequin-Artifact/src/keys \
         --sql_bench=true \
         --data_file_path /tmp/rwsql/rw-sql.json \
         --num_tables $NUM_TABLES \
         --num_keys_per_table $NUM_KEYS \
         --value_size -1 \
         --debug_stats \
         --stats_file=$stats_remote \
         $byz_flag \
         > $log_remote 2>&1 </dev/null &"
  ssh -f "${SSH_OPTS[@]}" "$host" "$cmd"
}

echo
echo "=== Launching shard 0 (6 replicas, f=1) ==="
for i in "${!S0_HOSTS[@]}"; do
  byz=0
  [ "$i" -ge $((S0_N - BYZ_S0)) ] && [ "$BYZ_S0" -gt 0 ] && byz=1
  printf "  [%s] s0/r%d on %-30s ... " \
    "$([ $byz = 1 ] && echo BYZ || echo ok )" "$i" "${S0_HOSTS[$i]#*@}"
  launch_server "${S0_HOSTS[$i]}" 0 "$i" "$byz"
  echo "launched"
done

echo
echo "=== Launching shard 1 (11 replicas, f=2) ==="
for i in "${!S1_HOSTS[@]}"; do
  byz=0
  [ "$i" -ge $((S1_N - BYZ_S1)) ] && [ "$BYZ_S1" -gt 0 ] && byz=1
  printf "  [%s] s1/r%d on %-30s ... " \
    "$([ $byz = 1 ] && echo BYZ || echo ok )" "$i" "${S1_HOSTS[$i]#*@}"
  launch_server "${S1_HOSTS[$i]}" 1 "$i" "$byz"
  echo "launched"
done

echo
echo "Waiting 10 s for servers to come up..."
sleep 10

# ---------- launch the lone client ----------
CLIENT_PIDS=()
echo
echo "=== Launching client ==="
for i in "${!CLIENT_HOSTS[@]}"; do
  host="${CLIENT_HOSTS[$i]}"
  client_id=$i
  log_remote="/tmp/pesto_client_${i}.log"
  stats_remote="/tmp/pesto_stats_${i}.json"

  cmd="source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1; \
       export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:\$LD_LIBRARY_PATH; \
       mkdir -p /tmp/rwsql && \
       cd /opt/Pequin-Artifact/src && \
       ./store/benchmark/async/benchmark \
         --config_path /tmp/shard.config \
         --num_groups $NUM_SHARDS --num_shards $NUM_SHARDS \
         --protocol_mode $PROTOCOL \
         --num_keys $NUM_KEYS \
         --benchmark rw-sql \
         --num_ops_txn $NUM_OPS \
         --exp_duration $DURATION \
         --client_id $client_id \
         --warmup_secs 5 --cooldown_secs 5 \
         --key_selector zipf --zipf_coefficient 0.5 \
         --stats_file $stats_remote \
         --indicus_key_path /opt/Pequin-Artifact/src/keys \
         --sql_bench=true \
         --data_file_path /tmp/rwsql/rw-sql.json \
         --num_tables $NUM_TABLES \
         --num_keys_per_table $NUM_KEYS \
         --value_size -1 \
         --max_range 100 \
         --rw_read_only=false \
         --fixed_range=true \
         --scan_as_point=true \
         --retry_aborted=true \
         --max_attempts=10 \
         > $log_remote 2>&1"

  printf "  client %d on %s ... " "$i" "${host#*@}"
  ssh "${SSH_OPTS[@]}" "$host" "$cmd" \
    > "$OUT_DIR/logs/client-${i}-launch.log" 2>&1 &
  CLIENT_PIDS+=($!)
  echo "launched (pid $!)"
done

# ---------- wait ----------
echo
TOTAL=$(( DURATION + 30 ))
echo "=== Waiting up to ${TOTAL}s for client to finish ==="
for elapsed in $(seq 1 "$TOTAL"); do
  sleep 1
  alive=0
  for pid in "${CLIENT_PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null && alive=$((alive+1))
  done
  printf "\r  elapsed: %ds / %ds   alive: %d/%d   " "$elapsed" "$TOTAL" "$alive" "$NUM_CLIENTS"
  [ "$alive" -eq 0 ] && break
done
echo

# ---------- scp stats BEFORE killing benchmark (avoid double-Cleanup empty bug) ----------
echo
echo "=== Pulling stats from client (BEFORE kill) ==="
for i in "${!CLIENT_HOSTS[@]}"; do
  host="${CLIENT_HOSTS[$i]}"
  printf "  client %d stats ... " "$i"
  scp -q "${SSH_OPTS[@]}" "$host:/tmp/pesto_stats_${i}.json" "$OUT_DIR/stats/client-${i}.json" \
    && echo ok || echo MISSING
done

# ---------- teardown ----------
echo
echo "=== Killing servers + benchmark on all $NUM_NODES nodes ==="
# SIGTERM (default) triggers server's Cleanup() → writes stats file. Sleep 3s
# before pulling so the file is fully written.
for t in "${TARGETS[@]:0:$NUM_NODES}"; do
  ssh "${SSH_OPTS[@]}" "$t" "killall -q server 2>/dev/null; killall -q benchmark 2>/dev/null; true" &
done
wait
sleep 3

# ---------- pull server stats (after SIGTERM-driven Cleanup write) ----------
echo
echo "=== Pulling server stats (membership_cert_loaded, ss_cert_*, ...) ==="
mkdir -p "$OUT_DIR/server_stats"
for i in "${!S0_HOSTS[@]}"; do
  scp -q "${SSH_OPTS[@]}" "${S0_HOSTS[$i]}:/tmp/pesto_server_stats_g0_r${i}.json" \
    "$OUT_DIR/server_stats/server-g0-r${i}.json" 2>/dev/null
done
for i in "${!S1_HOSTS[@]}"; do
  scp -q "${SSH_OPTS[@]}" "${S1_HOSTS[$i]}:/tmp/pesto_server_stats_g1_r${i}.json" \
    "$OUT_DIR/server_stats/server-g1-r${i}.json" 2>/dev/null
done

# ---------- pull logs ----------
echo
echo "=== Pulling logs ==="
for i in "${!CLIENT_HOSTS[@]}"; do
  scp -q "${SSH_OPTS[@]}" "${CLIENT_HOSTS[$i]}:/tmp/pesto_client_${i}.log" \
    "$OUT_DIR/logs/client-${i}.log" 2>/dev/null
done
for i in "${!S0_HOSTS[@]}"; do
  scp -q "${SSH_OPTS[@]}" "${S0_HOSTS[$i]}:/tmp/pesto_server_g0_r${i}.log" \
    "$OUT_DIR/logs/server-g0-r${i}.log" 2>/dev/null
done
for i in "${!S1_HOSTS[@]}"; do
  scp -q "${SSH_OPTS[@]}" "${S1_HOSTS[$i]}:/tmp/pesto_server_g1_r${i}.log" \
    "$OUT_DIR/logs/server-g1-r${i}.log" 2>/dev/null
done

# ---------- params ----------
cat > "$OUT_DIR/run_params.txt" <<EOF
TIMESTAMP=$TS
DURATION=$DURATION
S0_N=$S0_N S0_F=$S0_F BYZ_S0=$BYZ_S0
S1_N=$S1_N S1_F=$S1_F BYZ_S1=$BYZ_S1
BYZ_REPLICA_MODE=$BYZ_REPLICA_MODE
NUM_TABLES=$NUM_TABLES
NUM_KEYS=$NUM_KEYS
NUM_OPS=$NUM_OPS
PROTOCOL=$PROTOCOL
EOF

echo
echo "================ Summary ================"
echo "  Output: $OUT_DIR"
ok=0
for i in $(seq 0 $((NUM_CLIENTS-1))); do
  f="$OUT_DIR/stats/client-${i}.json"
  if [ -s "$f" ] && grep -q "total_commit_honest" "$f"; then
    c=$(grep -o '"total_commit_honest": *[0-9]*' "$f" | grep -o '[0-9]*')
    [ -n "$c" ] && [ "$c" -gt 0 ] && ok=1 && echo "  client $i: $c commits"
  fi
done
[ $ok = 1 ] && echo "  RESULT: PASS  (heterogeneous config booted + committed)" \
            || echo "  RESULT: FAIL  (no commits — check server logs for quorum hangs)"
