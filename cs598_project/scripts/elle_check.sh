#!/usr/bin/env bash
# elle_check.sh — merge per-client Elle JSON histories, sort by time,
# and run mini_elle.py on the result.
#
# Usage:  bash elle_check.sh <run_dir>
#   where <run_dir> is e.g. pesto-results/20260505T101800Z/
#   and contains elle/client-{0..N}.jsonl
#
# Output: prints mini_elle's verdict, exits 0 on PASS, non-zero on FAIL.

set -uo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <run_dir>" >&2
  exit 2
fi
RUN_DIR=$1
ELLE_DIR="$RUN_DIR/elle"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$ELLE_DIR" ]; then
  echo "ERROR: $ELLE_DIR not found (was the run done with --elle_history_path?)" >&2
  exit 2
fi

shopt -s nullglob
files=( "$ELLE_DIR"/client-*.jsonl )
if [ ${#files[@]} -eq 0 ]; then
  echo "ERROR: no client-*.jsonl files in $ELLE_DIR" >&2
  exit 2
fi

# Merge: concat all, sort by "time" field. Each line is a self-contained
# JSON object with a "time" key (nanoseconds).
MERGED="$RUN_DIR/elle/merged.jsonl"
python3 -c "
import json, sys
events = []
for path in [$(printf '\"%s\",' "${files[@]}")]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                ev = json.loads(line)
                events.append(ev)
            except json.JSONDecodeError as e:
                print(f'WARN: skip bad line in {path}: {e}', file=sys.stderr)
events.sort(key=lambda e: e.get('time', 0))
# Re-assign monotonic indices in merged order
for i, e in enumerate(events):
    e['index'] = i
with open('$MERGED', 'w') as out:
    for e in events:
        out.write(json.dumps(e, separators=(',', ':')) + '\n')
print(f'merged {len(events)} events from {len([$(printf '\"%s\",' "${files[@]}")])} files into {\"$MERGED\"}')
"

echo
python3 "$SCRIPT_DIR/mini_elle.py" "$MERGED"
