#!/usr/bin/env bash
# Apply or remove WAN-like one-way egress delay on the shard-1 server hosts.
# Result: cross-shard traffic sees +DELAY each way (so RTT increases by 2*DELAY).
# Intra-shard-1 traffic also sees the delay; acceptable artifact for a quick
# geo-distributed stress test.
#
# Usage:
#   bash scripts/apply_wan_delay.sh apply 25     # add 25ms egress delay
#   bash scripts/apply_wan_delay.sh remove

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAB="${SCRIPT_DIR}/../lab_ssh.txt"
ACTION="${1:-show}"
DELAY_MS="${2:-25}"
# Auto-detect the default outbound interface per host (works for mixed hardware
# where some nodes use eno1, eno49np0, eno33np0, eno12399, etc.)
detect_iface() {
  local host="$1"
  timeout 5 ssh -o ConnectTimeout=4 "$host" \
    "ip route get 8.8.8.8 | head -1 | awk '{for(i=1;i<=NF;i++) if(\$i==\"dev\") print \$(i+1)}'" 2>/dev/null
}

# Shard 1 hosts are TARGETS[N_SHARD0 .. N_SHARD0+N_SHARD0-1] in heterogeneous mode.
# For our default (n=6 f=1), shard 0 has 6 replicas and shard 1 starts at index 6.
SHARD0_SIZE="${SHARD0_SIZE:-6}"
mapfile -t TARGETS < <(awk 'NF>=2 && $1=="ssh" {print $2}' "$LAB")
SHARD1_HOSTS=("${TARGETS[@]:SHARD0_SIZE:SHARD0_SIZE}")

apply() {
  for host in "${SHARD1_HOSTS[@]}"; do
    short="${host##*@}"; short="${short%%.*}"
    iface=$(detect_iface "$host")
    if [ -z "$iface" ]; then echo "  $short FAIL (no iface)"; continue; fi
    if ssh "$host" "sudo -n tc qdisc replace dev $iface root netem delay ${DELAY_MS}ms 2>&1 | head" 2>&1 | grep -q "RTNETLINK\|cannot"; then
      echo "  $short FAIL"
    else
      echo "  $short ($iface) delay+=${DELAY_MS}ms"
    fi
  done
}
remove() {
  for host in "${SHARD1_HOSTS[@]}"; do
    short="${host##*@}"; short="${short%%.*}"
    iface=$(detect_iface "$host")
    if [ -z "$iface" ]; then echo "  $short (down)"; continue; fi
    ssh "$host" "sudo -n tc qdisc del dev $iface root 2>&1 | head" >/dev/null 2>&1 \
      && echo "  $short ($iface) clean" || echo "  $short (already clean)"
  done
}
show() {
  for host in "${SHARD1_HOSTS[@]}"; do
    short="${host##*@}"; short="${short%%.*}"
    iface=$(detect_iface "$host")
    if [ -z "$iface" ]; then echo "  $short: DOWN"; continue; fi
    out=$(ssh "$host" "tc qdisc show dev $iface 2>&1" 2>&1 | head -2 | tr '\n' '|')
    echo "  $short ($iface): $out"
  done
}

case "$ACTION" in
  apply)  echo "Applying ${DELAY_MS}ms delay to 6 shard-1 hosts"; apply ;;
  remove) echo "Removing delay from 6 shard-1 hosts"; remove ;;
  show)   echo "Current qdisc on shard-1 hosts:"; show ;;
  *) echo "Usage: $0 {apply|remove|show} [delay_ms]"; exit 1 ;;
esac
