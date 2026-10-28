"""Report actual observations only; never generate illustrative performance data."""
import argparse
import json
from pathlib import Path
import statistics

parser = argparse.ArgumentParser()
parser.add_argument('--prefix', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent/'results'
lines = ['# Measured application performance', '',
         'Fresh TCP connections; 200 sequential 4096-byte echoes per sample. Throughput is outgoing payload goodput, not link capacity.', '',
         '| Run | Success / total | Connect median ms | First echo median ms | Steady echo median ms | Goodput median Mbps |',
         '|---|---:|---:|---:|---:|---:|']
by_mode = {'baseline': [], 'firewall': []}
for path in sorted(root.glob(args.prefix+'*/benchmark.jsonl')):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    good = [r for r in rows if r['success']]
    if not good:
        lines.append(f'| {path.parent.name} | 0 / {len(rows)} | — | — | — | — |')
        continue
    keys = ['connect_ms','first_echo_ms','steady_median_ms','application_mbps']
    metrics = [statistics.median(r[k] for r in good) for k in keys]
    lines.append(f'| {path.parent.name} | {len(good)} / {len(rows)} | '+' | '.join(f'{x:.3f}' for x in metrics)+' |')
    by_mode[good[0]['mode']].append(dict(zip(keys, metrics)))
if not any(by_mode.values()):
    raise SystemExit('No benchmark files matched; run the suite on Ubuntu first.')
lines += ['', '## Comparison across run medians', '']
for key in ['connect_ms','first_echo_ms','steady_median_ms','application_mbps']:
    if all(by_mode.values()):
        baseline = statistics.median(r[key] for r in by_mode['baseline'])
        firewall = statistics.median(r[key] for r in by_mode['firewall'])
        delta = 100*(firewall-baseline)/baseline if baseline else float('nan')
        lines.append(f'- {key}: baseline {baseline:.3f}, firewall {firewall:.3f}; change {delta:+.1f}%.')
lines += ['', 'Negative latency change is faster; negative goodput change is slower. Small differences can be VM noise. Report each round, sample counts and failures. First echo includes server connection logging; steady echo excludes it.', '',
          'Blocking measurements are in each demo/security.jsonl (BLOCK_REQUEST, BLOCK_CONFIRMED, RECOVER) and demo/recovery.json. Barrier time confirms switch processing, not first packet loss; recovery probes provide an observed bound rather than an exact expiry timestamp.']
report = root/(args.prefix+'-summary.md')
report.write_text('\n'.join(lines)+'\n')
print(report)
