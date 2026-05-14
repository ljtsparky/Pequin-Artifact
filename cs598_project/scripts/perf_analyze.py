#!/usr/bin/env python3
"""perf_analyze.py — extract throughput, latency percentiles, and the
new µs crypto counters from a Pesto pesto-results/<TS>/ directory.

Usage:
    python3 scripts/perf_analyze.py [--csv] <run_dir> [<run_dir> ...]
"""

import json, re, glob, sys
from pathlib import Path

LAT_RE = re.compile(r'(Median|Average|90th percentile|95th percentile|99th percentile) latency is (\d+) ns')
LABEL = {'Median':'p50','Average':'avg','90th percentile':'p90','95th percentile':'p95','99th percentile':'p99'}

def parse_run(run_dir):
    run_dir = Path(run_dir)
    params = {}
    pf = run_dir / 'run_params.txt'
    if pf.exists():
        for line in pf.read_text().splitlines():
            if '=' in line:
                k,v = line.split('=',1); params[k]=v
    duration = int(params.get('DURATION','60'))
    nt = params.get('NUM_TABLES','?')
    ops = params.get('NUM_OPS','?')
    nc = params.get('NUM_CLIENTS','?')
    eager = params.get('PEQUIN_EAGER','?')
    byz = params.get('BYZ_PER_SHARD','0')
    bmode = params.get('BYZ_REPLICA_MODE','-') if byz != '0' else '-'
    bench = params.get('BENCHMARK','rw-sql')

    # Throughput: sum committed across client stats
    total_commit = 0
    total_attempts = 0
    total_aborts = 0
    commit_keys = ['rw_sql_committed','tpcc_committed','total_commit_honest']
    attempt_keys = ['rw_sql_attempts','tpcc_attempts']
    for f in glob.glob(str(run_dir/'stats/client-*.json')):
        d = json.load(open(f))
        for k in commit_keys:
            if k in d: total_commit += d[k]; break
        for k in attempt_keys:
            if k in d: total_attempts += d[k]; break
        total_aborts  += d.get('total_abort_honest', 0)
    tput = total_commit / duration if duration else 0

    # Latency: client log "CooldownDone" line
    lats = {lab:[] for lab in LABEL.values()}
    for f in glob.glob(str(run_dir/'logs/client-*.log')):
        if 'launch' in f: continue
        try:
            text = open(f, errors='ignore').read()
        except Exception:
            continue
        for m in LAT_RE.finditer(text):
            lab = LABEL[m.group(1)]
            ns = int(m.group(2))
            lats[lab].append(ns/1e6)
    avg_lats = {k: (sum(v)/len(v) if v else None) for k,v in lats.items()}

    # Server-side µs counters
    sign_us_total = sign_n = verify_us_total = verify_n = 0
    v3_attached = v3_verifications = 0
    twin_perts = 0
    for f in glob.glob(str(run_dir/'server_stats/server-g*.json')):
        d = json.load(open(f))
        sign_us_total      += d.get('ss_cert_vote_sign_micros_total', 0)
        sign_n             += d.get('ss_cert_vote_sign_count', 0)
        verify_us_total    += d.get('ss_cert_verify_micros_total', 0)
        verify_n           += d.get('ss_cert_verify_count', 0)
        v3_attached        += d.get('ss_cert_v3_votes_attached', 0)
        v3_verifications   += d.get('ss_cert_verifications_done', 0)
        twin_perts         += d.get('byz_twin_perturbations', 0)
    sign_avg = (sign_us_total/sign_n) if sign_n else None
    verify_avg = (verify_us_total/verify_n) if verify_n else None

    return {
        'run': run_dir.name, 'NT': nt, 'OPS': ops, 'NC': nc, 'eager': eager,
        'byz': byz, 'mode': bmode, 'bench': bench, 'duration_s': duration,
        'commit_total': total_commit, 'attempt_total': total_attempts,
        'abort_total': total_aborts, 'throughput_txs': tput,
        'p50_ms': avg_lats['p50'], 'p90_ms': avg_lats['p90'],
        'p95_ms': avg_lats['p95'], 'p99_ms': avg_lats['p99'],
        'sign_avg_us': sign_avg, 'sign_count': sign_n,
        'verify_avg_us': verify_avg, 'verify_count': verify_n,
        'v3_attached': v3_attached, 'verify_done': v3_verifications,
        'twin_perts': twin_perts,
    }

def fmt(x, w=8, p=1):
    if x is None: return ' '*w
    if isinstance(x,(int,)): return f'{x:>{w}d}'
    return f'{x:>{w}.{p}f}'

if __name__ == '__main__':
    args = sys.argv[1:]
    csv = '--csv' in args
    if csv: args.remove('--csv')
    rows = [parse_run(p) for p in args]
    if csv:
        keys = list(rows[0].keys())
        print(','.join(keys))
        for r in rows: print(','.join(str(r[k]) if r[k] is not None else '' for k in keys))
    else:
        hdr = ['run','bench','NT','OPS','NC','eager','byz/mode','commit','tput','p50','p95','p99','sign_µs','verify_µs','v3_done']
        print(' | '.join(f'{h:>9}' for h in hdr))
        print('-'*150)
        for r in rows:
            bm = f"{r['byz']}/{r['mode']}" if r['byz']!='0' else '0/-'
            print(' | '.join([
                f"{r['run'][-9:]:>9}", f"{r['bench']:>9}", f"{r['NT']:>9}", f"{r['OPS']:>9}",
                f"{r['NC']:>9}", f"{r['eager']:>9}", f"{bm:>9}",
                fmt(r['commit_total'],9,0), fmt(r['throughput_txs'],9,1),
                fmt(r['p50_ms'],9,1), fmt(r['p95_ms'],9,1), fmt(r['p99_ms'],9,1),
                fmt(r['sign_avg_us'],9,1), fmt(r['verify_avg_us'],9,1),
                fmt(r['verify_done'],9,0),
            ]))
