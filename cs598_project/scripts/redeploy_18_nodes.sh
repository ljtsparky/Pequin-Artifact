#!/usr/bin/env bash
# redeploy_18_nodes.sh — pull latest cross-shard-membership branch on
# all 18 CloudLab nodes and rebuild the changed binaries (server +
# benchmark). Idempotent + parallel.
#
# Usage: bash redeploy_18_nodes.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_SSH="${LAB_SSH:-${SCRIPT_DIR}/../lab_ssh.txt}"

SSH_OPTS=( -i /home/student/.ssh/id_ed25519
           -o StrictHostKeyChecking=no
           -o BatchMode=yes
           -o UserKnownHostsFile=/dev/null
           -o LogLevel=ERROR
           -o ConnectTimeout=10 )

mapfile -t TARGETS < <(awk 'NF>=2 && $1=="ssh" {print $2}' "$LAB_SSH")
echo "=== Pulling + rebuilding on ${#TARGETS[@]} nodes ==="

# We need to source setvars.sh so libtbb is found AT BUILD TIME.
# We rebuild only the two binaries we care about: server + benchmark.
REMOTE_CMD='set -e
cd /opt/Pequin-Artifact
git fetch origin cross-shard-membership 2>&1 | tail -2
git checkout cross-shard-membership 2>&1 | tail -1
BEFORE=$(git rev-parse --short HEAD)
git pull --ff-only origin cross-shard-membership 2>&1 | tail -2
AFTER=$(git rev-parse --short HEAD)
echo "  HEAD: $BEFORE -> $AFTER"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "  no change; skip rebuild"
  exit 0
fi
source /opt/intel/oneapi/setvars.sh --force >/dev/null 2>&1 || true
export LD_LIBRARY_PATH=/usr/lib/jvm/java-11-openjdk-amd64/lib/server:$LD_LIBRARY_PATH
cd src
make store/server store/benchmark/async/benchmark 2>&1 | tail -5'

# Run in parallel. Save per-node log; print PASS/FAIL summary.
TS=$(date -u +"%Y%m%dT%H%M%SZ")
LOG_DIR=/tmp/redeploy_${TS}
mkdir -p "$LOG_DIR"
PIDS=()
for t in "${TARGETS[@]}"; do
  host="${t#*@}"
  ( ssh "${SSH_OPTS[@]}" "$t" "$REMOTE_CMD" > "$LOG_DIR/$host.log" 2>&1
    rc=$?
    if [ $rc -eq 0 ]; then echo "  [ok  ] $host"; else echo "  [FAIL] $host (rc=$rc)"; fi
  ) &
  PIDS+=($!)
done
wait
echo
echo "Per-node logs in $LOG_DIR/"
echo "=== Summary HEAD per node ==="
for f in "$LOG_DIR"/*.log; do
  h=$(basename "$f" .log)
  head_line=$(grep "HEAD:" "$f" 2>/dev/null | head -1)
  echo "  $h: $head_line"
done
