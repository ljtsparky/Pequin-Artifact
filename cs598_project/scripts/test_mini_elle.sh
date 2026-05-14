#!/usr/bin/env bash
# test_mini_elle.sh — smoke test for mini_elle.py.
# Two synthetic histories: one safe (PASS), one cyclic (FAIL).

set -e
cd "$(dirname "$0")"

echo "=========================================="
echo "TEST 1 — safe history (should PASS)"
echo "=========================================="

cat > /tmp/elle_safe.jsonl <<'EOF'
{"index":0,"type":"invoke","process":1,"time":1000,"value":[["append","x",1]]}
{"index":1,"type":"ok",    "process":1,"time":1010,"value":[["append","x",1]]}
{"index":2,"type":"invoke","process":2,"time":1020,"value":[["r","x",null]]}
{"index":3,"type":"ok",    "process":2,"time":1030,"value":[["r","x",[1]]]}
{"index":4,"type":"invoke","process":1,"time":1040,"value":[["append","x",2]]}
{"index":5,"type":"ok",    "process":1,"time":1050,"value":[["append","x",2]]}
{"index":6,"type":"invoke","process":2,"time":1060,"value":[["r","x",null]]}
{"index":7,"type":"ok",    "process":2,"time":1070,"value":[["r","x",[1,2]]]}
EOF

python3 mini_elle.py /tmp/elle_safe.jsonl
echo

echo "=========================================="
echo "TEST 2 — cyclic history (should FAIL)"
echo "=========================================="
# Construct G2 anti-dep cycle:
#   T1 reads x=[]   (sees no append on x)
#   T1 appends y=1
#   T2 reads y=[]   (sees no append on y)
#   T2 appends x=1
# T1 anti-deps T2 (T1's read of x missed T2's append)
# T2 anti-deps T1 (T2's read of y missed T1's append)
# => cycle T1 <-> T2
cat > /tmp/elle_cyclic.jsonl <<'EOF'
{"index":0,"type":"invoke","process":1,"time":1000,"value":[["r","x",null],["append","y",1]]}
{"index":1,"type":"invoke","process":2,"time":1001,"value":[["r","y",null],["append","x",1]]}
{"index":2,"type":"ok",    "process":1,"time":1010,"value":[["r","x",[]],["append","y",1]]}
{"index":3,"type":"ok",    "process":2,"time":1011,"value":[["r","y",[]],["append","x",1]]}
EOF

python3 mini_elle.py /tmp/elle_cyclic.jsonl && echo "BUG: should have failed!" || echo "expected FAIL — OK"

echo
echo "=========================================="
echo "TEST 3 — single-process append + read"
echo "=========================================="
cat > /tmp/elle_intra.jsonl <<'EOF'
{"index":0,"type":"invoke","process":1,"time":1000,"value":[["append","x",10]]}
{"index":1,"type":"ok",    "process":1,"time":1010,"value":[["append","x",10]]}
{"index":2,"type":"invoke","process":1,"time":1020,"value":[["r","x",null]]}
{"index":3,"type":"ok",    "process":1,"time":1030,"value":[["r","x",[10]]]}
EOF

python3 mini_elle.py /tmp/elle_intra.jsonl
