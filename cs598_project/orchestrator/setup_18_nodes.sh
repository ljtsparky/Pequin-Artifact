#!/usr/bin/env bash
#
# setup_18_nodes.sh — one-shot setup for a fresh 18-node CloudLab experiment
#
# Run from THIS VM (which has its SSH key registered with CloudLab portal).
# Reads node hostnames from lab_ssh.txt (format: "ssh Jiatong@amdNNN.utah.cloudlab.us")
# and does, on each node:
#
#   1. install geni-get key + add pubkey to authorized_keys → inter-node SSH
#   2. (sanity) confirm /opt/Pequin-Artifact is on cross-shard-membership branch
#   3. (sanity) confirm the 3 critical binaries exist
#   4. (sanity) confirm src/keys/ has 256 entries (128 keypair × 2 files)
#
# After step 1 succeeds on ALL nodes, the LAST step rsyncs the keys/ directory
# from node 0 to nodes 1..17 — so all 18 nodes have the SAME 256 keys (BFT
# crypto requires identical keysets across replicas).
#
# Usage:
#   bash /home/student/CS598FTS/setup_18_nodes.sh
#
# Env overrides:
#   LAB_SSH_FILE  path to file with node hostnames (default: lab_ssh.txt next to this script)
#   PARALLEL      set to 1 to run per-node setup in parallel (faster, noisier output)

set -uo pipefail   # NOT -e: keep going even if one node fails so we report all

# ---------- locate inputs ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB_SSH_FILE="${LAB_SSH_FILE:-${SCRIPT_DIR}/lab_ssh.txt}"

if [ ! -f "$LAB_SSH_FILE" ]; then
  echo "ERROR: $LAB_SSH_FILE not found." >&2
  exit 1
fi

# Extract user@host from each line. Lines look like:
#   ssh Jiatong@amd225.utah.cloudlab.us
# We grab the second token, which is the user@host part.
mapfile -t TARGETS < <(awk 'NF>=2 && $1=="ssh" {print $2}' "$LAB_SSH_FILE")

if [ "${#TARGETS[@]}" -ne 18 ]; then
  echo "WARN: expected 18 entries in $LAB_SSH_FILE, got ${#TARGETS[@]}." >&2
  echo "Continuing anyway with ${#TARGETS[@]} target(s)." >&2
fi

echo "Targets:"
for t in "${TARGETS[@]}"; do echo "  $t"; done
echo

# Common SSH options. Disable host-key checking for the FIRST connection
# (CloudLab regenerates host keys per experiment so prior known_hosts is stale).
SSH_OPTS=(
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
)

# ---------- per-node setup ----------
# This block runs ON EACH NODE (piped via ssh).
NODE_SETUP_SCRIPT='
set -u
ok=0; bad=0
note() { printf "  %s\n" "$*"; }

# (1) inter-node SSH key (geni-get)
if [ -s "$HOME/.ssh/id_rsa" ]; then
  note "[skip] geni-get id_rsa already present"
else
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  if /usr/bin/geni-get key > "$HOME/.ssh/id_rsa" 2>/dev/null; then
    chmod 600 "$HOME/.ssh/id_rsa"
    ssh-keygen -y -f "$HOME/.ssh/id_rsa" > "$HOME/.ssh/id_rsa.pub" 2>/dev/null
    grep -qf "$HOME/.ssh/id_rsa.pub" "$HOME/.ssh/authorized_keys" 2>/dev/null \
      || cat "$HOME/.ssh/id_rsa.pub" >> "$HOME/.ssh/authorized_keys"
    chmod 644 "$HOME/.ssh/authorized_keys"
    note "[ok]   geni-get key installed"
  else
    note "[FAIL] geni-get key not available — inter-node SSH will not work"
    bad=$((bad+1))
  fi
fi

# (2) repo state
if [ -d /opt/Pequin-Artifact ]; then
  cd /opt/Pequin-Artifact
  branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
  head=$(git log --oneline -1 2>/dev/null | head -c 40)
  note "[ok]   repo: branch=$branch  head=$head"
else
  note "[FAIL] /opt/Pequin-Artifact missing"
  bad=$((bad+1))
fi

# (3) critical binaries
for b in store/server store/benchmark/async/benchmark store/pequinstore/tests/membership_test; do
  if [ -x "/opt/Pequin-Artifact/src/$b" ]; then
    note "[ok]   binary: $b"
  else
    note "[FAIL] binary missing: $b"
    bad=$((bad+1))
  fi
done

# (4) keys directory
key_count=$(ls /opt/Pequin-Artifact/src/keys 2>/dev/null | wc -l)
if [ "$key_count" -ge 256 ]; then
  note "[ok]   keys: $key_count files in /opt/Pequin-Artifact/src/keys"
else
  note "[WARN] keys: only $key_count files (expected ≥ 256). Will sync from node0."
fi

if [ "$bad" -gt 0 ]; then
  echo "STATUS: $bad failure(s)"
  exit 1
else
  echo "STATUS: ok"
  exit 0
fi
'

# ---------- run setup on each node ----------
declare -A RESULT
run_one() {
  local target="$1"
  local log="/tmp/setup_$(echo "$target" | tr "@." "_").log"
  printf "\n=== %s ===\n" "$target"
  if ssh "${SSH_OPTS[@]}" "$target" "bash -s" <<< "$NODE_SETUP_SCRIPT" 2>&1 | tee "$log" \
       | grep -q "^STATUS: ok"; then
    RESULT[$target]=ok
  else
    RESULT[$target]=fail
  fi
}

if [ "${PARALLEL:-0}" = "1" ]; then
  # Run all 18 in parallel (output interleaves)
  for target in "${TARGETS[@]}"; do
    run_one "$target" &
  done
  wait
else
  for target in "${TARGETS[@]}"; do
    run_one "$target"
  done
fi

# ---------- sync keys/ from node0 to all others ----------
NODE0="${TARGETS[0]}"
echo
echo "=== Syncing /opt/Pequin-Artifact/src/keys/ from $NODE0 to other 17 nodes ==="
echo "(BFT requires every replica to share the same Ed25519 keyset.)"

# Verify node0 has keys before pushing
node0_count=$(ssh "${SSH_OPTS[@]}" "$NODE0" "ls /opt/Pequin-Artifact/src/keys 2>/dev/null | wc -l")
if [ "${node0_count:-0}" -lt 256 ]; then
  echo "  [FAIL] node0 ($NODE0) keys/ has only $node0_count files."
  echo "         Generating fresh keys on node0 (one-time, ~30s)..."
  ssh "${SSH_OPTS[@]}" "$NODE0" "cd /opt/Pequin-Artifact/src && ./keygen.sh"
  node0_count=$(ssh "${SSH_OPTS[@]}" "$NODE0" "ls /opt/Pequin-Artifact/src/keys 2>/dev/null | wc -l")
  echo "         Now node0 has $node0_count key files."
fi

# Tar from node0, distribute via scp+untar (one-shot, no rsync needed)
TAR_TMP="/tmp/pesto_keys_$$.tgz"
ssh "${SSH_OPTS[@]}" "$NODE0" "tar -C /opt/Pequin-Artifact/src -czf $TAR_TMP keys/"
scp "${SSH_OPTS[@]}" "$NODE0:$TAR_TMP" "/tmp/pesto_keys.tgz"

for target in "${TARGETS[@]:1}"; do
  printf "  -> %-50s " "$target"
  scp -q "${SSH_OPTS[@]}" "/tmp/pesto_keys.tgz" "$target:/tmp/pesto_keys.tgz" \
    && ssh "${SSH_OPTS[@]}" "$target" "tar -C /opt/Pequin-Artifact/src -xzf /tmp/pesto_keys.tgz && rm -f /tmp/pesto_keys.tgz" \
    && echo "ok" \
    || echo "FAIL"
done

# Cleanup
ssh "${SSH_OPTS[@]}" "$NODE0" "rm -f $TAR_TMP" 2>/dev/null
rm -f "/tmp/pesto_keys.tgz"

# ---------- verify inter-node SSH ----------
# Build the per-host list ON THIS VM from lab_ssh.txt (no hardcoding).
# We extract just the host part (after '@') and pass it as a newline-separated
# string into the remote shell. The remote node loops, skipping its own name.
echo
echo "=== Inter-node SSH check (from $NODE0 to other 17 nodes) ==="

HOSTS_LIST=""
for t in "${TARGETS[@]}"; do
  HOSTS_LIST+="${t#*@}"$'\n'   # everything after the '@'
done

ssh "${SSH_OPTS[@]}" "$NODE0" "HOSTS=\"$HOSTS_LIST\"; me=\$(hostname -f); for h in \$HOSTS; do [ \"\$h\" = \"\$me\" ] && continue; printf '  %-40s ' \"\$h\"; ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 \"\$h\" 'echo ok' 2>&1 | head -1; done"

# ---------- summary ----------
echo
echo "================ Summary ================"
ok_count=0
fail_count=0
for target in "${TARGETS[@]}"; do
  status="${RESULT[$target]:-unknown}"
  printf "  %-50s %s\n" "$target" "$status"
  [ "$status" = "ok" ] && ok_count=$((ok_count+1)) || fail_count=$((fail_count+1))
done
echo
echo "  Nodes OK:   $ok_count"
echo "  Nodes FAIL: $fail_count"
echo
echo "Detailed per-node logs in /tmp/setup_*.log on this VM."

if [ "$fail_count" -eq 0 ]; then
  echo "  ALL 18 nodes ready. Proceed to experiment configs."
  exit 0
else
  exit 1
fi
