#!/usr/bin/env bash
#
# Run all upstream Pequin unit tests + our new membership_test, on a single
# node, no networking required.
#
# Sanity: these are pure-functional tests that previously passed on upstream.
# Our cross-shard work only ADDED code paths; if any of these now FAIL, it
# means we regressed something.  SKIP entries need external schema files we
# don't have locally and are noted in the README.
#
# Run from anywhere on a CloudLab node:
#   bash /opt/Pequin-Artifact/src/0_local_test_outputs/configs/run_unit_tests.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TESTS_DIR="${SRC_DIR}/store/pequinstore/tests"
LOG_DIR="${SRC_DIR}/0_local_test_outputs/unit_test_logs"

mkdir -p "$LOG_DIR"
cd "$SRC_DIR"

# (test_binary, requires_external_files, short_description)
declare -a TESTS=(
  "membership_test|no|cross-shard membership cert + per-group quorums (OURS)"
  "tbb_test|no|Intel TBB concurrent map sanity"
  "proto_bench|no|protobuf serialization micro-benchmark"
  "compression_test|no|payload compression round-trip"
  "snapshot_test|no|snapshot manager unit tests"
  "table_store_interface_test|no|table store API"
  "table_loader_test|yes|loads on-disk schema (needs schema file)"
  "sql_interpreter_test|yes|parses SQL DDL (needs schema file)"
)

PASS=0
FAIL=0
SKIP=0
FAILED_NAMES=()

for entry in "${TESTS[@]}"; do
  IFS='|' read -r name needs_files desc <<< "$entry"
  bin="${TESTS_DIR}/${name}"
  log="${LOG_DIR}/${name}.log"

  printf "%-32s  " "$name"

  if [ ! -x "$bin" ]; then
    printf "SKIP  (binary missing — try: make %s)\n" "store/pequinstore/tests/${name}"
    SKIP=$((SKIP+1))
    continue
  fi

  # Run with 60s timeout; capture all output to log
  timeout 60 "$bin" > "$log" 2>&1
  rc=$?

  if [ $rc -eq 0 ]; then
    printf "PASS  (%s)\n" "$desc"
    PASS=$((PASS+1))
  elif [ $rc -eq 124 ]; then
    printf "TIMEOUT (>60s) — log: %s\n" "$log"
    FAIL=$((FAIL+1))
    FAILED_NAMES+=("$name")
  else
    if [ "$needs_files" = "yes" ]; then
      # Tests requiring external schema files often fail with file-not-found
      if grep -qiE "no such file|cannot open|file_path" "$log" 2>/dev/null; then
        printf "SKIP  (needs schema file we don't have)\n"
        SKIP=$((SKIP+1))
        continue
      fi
    fi
    printf "FAIL  (exit %d) — log: %s\n" "$rc" "$log"
    FAIL=$((FAIL+1))
    FAILED_NAMES+=("$name")
  fi
done

echo
echo "================ Summary ================"
echo "  PASS:  $PASS"
echo "  SKIP:  $SKIP   (external dependency, not a regression)"
echo "  FAIL:  $FAIL"

if [ $FAIL -gt 0 ]; then
  echo
  echo "Failed tests (these would be regressions if previously passing on upstream):"
  for n in "${FAILED_NAMES[@]}"; do
    echo "  - $n"
    echo "    last 10 lines of ${LOG_DIR}/${n}.log:"
    tail -10 "${LOG_DIR}/${n}.log" 2>/dev/null | sed 's/^/      /'
  done
  exit 1
fi

echo
echo "All non-skipped tests passed.  Cross-shard work appears non-regressive."
