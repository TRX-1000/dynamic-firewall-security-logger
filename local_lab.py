#!/usr/bin/env python3
"""Mac/Windows/Linux lab; Python standard library only. No admin or pip needed."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import threading
import time
from client import request
from logger_server import Logger
from server import Server, Handler
from local_firewall import LocalFirewall, Proxy

ROOT = Path(__file__).resolve().parent

class LocalServer(Server):
    daemon_threads = False
    block_on_close = True

class LocalLab:
    def __init__(self, output, mode='firewall', base_port=0, block_seconds=10):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.services, self.threads = [], []
        self.fw = None
        self.mode, self.base_port, self.block_seconds = mode, base_port, block_seconds

    def start_service(self, service):
        self.services.append(service)
        thread = threading.Thread(target=service.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        self.threads.append(thread)
        return service.server_address[1]

    def __enter__(self):
        try:
            logger_port = self.start_service(Logger(('127.0.0.1',0), self.output/'security.jsonl'))
            backends = {}
            for logical_port in (5000, 9999):
                server = LocalServer(('127.0.0.1',0), Handler)
                server.logger_host, server.logger_port = '127.0.0.1', logger_port
                backends[logical_port] = self.start_service(server)
            self.backends = backends
            self.fw = LocalFirewall(self.output, logger_port, self.mode, self.block_seconds)
            self.ports = {}
            roles = [('h1',5000), ('h2',5000), ('h1',9999), ('h2',9999)]
            for number, (host, logical_port) in enumerate(roles, 1):
                port = self.base_port+number if self.base_port else 0
                source = '10.0.0.'+host[-1]
                self.ports[(host,logical_port)] = self.start_service(
                    Proxy(port, source, logical_port, backends[logical_port], self.fw))
            mapping = [{'logical_client':h,'logical_service_port':p,'localhost_port':actual}
                       for (h,p),actual in self.ports.items()]
            (self.output/'ports.json').write_text(json.dumps(mapping,indent=2), encoding='utf-8')
            print(f'LOCAL PROXY LAB ({self.mode}) — not Mininet/OpenFlow', flush=True)
            for item in mapping:
                print(f"  {item['logical_client']} -> service {item['logical_service_port']}: 127.0.0.1:{item['localhost_port']}", flush=True)
            print(f'Logs: {self.output}', flush=True)
            return self
        except BaseException:
            self.close()
            raise

    def probe(self, host='h2', port=5000, **kwargs):
        result = request('127.0.0.1', self.ports[(host,port)], **kwargs)
        result.update(environment='localhost-proxy', mode=self.mode, logical_client=host, logical_port=port)
        return result

    def close(self):
        if self.fw:
            self.fw.stopped.set()
            self.fw.timer.join(timeout=2)
        # Keep logger (first service) alive while proxies/apps finish and the
        # asynchronous firewall queue drains.
        for service in reversed(self.services[1:]):
            service.shutdown()
            service.server_close()
        if self.fw:
            self.fw.close()
        if self.services:
            self.services[0].shutdown()
            self.services[0].server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.services.clear()

    def __exit__(self, *args):
        self.close()


def demo(lab):
    checks = []
    def check(name, expected=True, **kwargs):
        result = lab.probe(timeout=.35, **kwargs)
        result.update(check=name, expected=expected)
        checks.append(result)
        (lab.output/'demo.json').write_text(json.dumps(checks,indent=2), encoding='utf-8')
        assert result['success'] == expected, result
        if not expected:
            assert result['error'].startswith('TimeoutError:'), result
        print('PASS:', name, flush=True)
        return result
    # Prove forbidden listener exists independently of the filtering proxy.
    assert request('127.0.0.1',lab.backends[9999],timeout=2)['success']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(lab.probe,host=h,count=20,timeout=2) for h in ('h1','h2')]
        assert all(f.result()['success'] for f in futures)
    print('PASS: concurrent clients', flush=True)
    check('h1 allowed',host='h1')
    check('h2 allowed')
    for index in range(3):
        check(f'unauthorized connection {index+1}',expected=False,port=9999)
    check('blocked h2 cannot use allowed service',expected=False)
    check('h1 unaffected',host='h1')
    print(f'Waiting for automatic recovery (~{lab.block_seconds} seconds from third attempt)...',flush=True)
    deadline = time.monotonic()+lab.block_seconds+3
    while time.monotonic()<deadline:
        if not lab.fw.is_blocked('10.0.0.2'):
            break
        time.sleep(.05)
    else:
        raise AssertionError('Recovery deadline exceeded')
    check('h2 automatically recovered')
    check('forbidden service remains forbidden',expected=False,port=9999)
    lab.fw.queue.join()
    events = [json.loads(line) for line in (lab.output/'security.jsonl').read_text(encoding='utf-8').splitlines()]
    kinds = {e['kind'] for e in events if e['component']=='local-proxy'}
    assert {'ALLOW','DENY','BLOCK','BLOCKED','RECOVER'} <= kinds, kinds
    assert not {'PROXY_ERROR'} & kinds, kinds
    print('LOCAL DEMO PASSED (application/proxy behavior only)',flush=True)


def benchmark(output, samples):
    results = []
    # Same proxy and logger in both modes; only policy enforcement changes.
    for mode in ('baseline','firewall'):
        with LocalLab(output/mode, mode=mode) as lab:
            assert lab.probe(host='h1',count=5,timeout=2)['success']
            if mode=='baseline':
                assert lab.probe(port=9999,timeout=2)['success']
            for index in range(samples):
                row = lab.probe(host='h1',count=100,size=4096,timeout=2)
                row['sample'] = index
                results.append(row)
                assert row['success'], row
    (output/'local-benchmark.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in results),encoding='utf-8')
    lines = ['# LOCAL proxy benchmark — not SDN results', '',
             'One baseline run followed by one firewall run; exploratory debugging only. OS scheduling, Python proxy and filesystem logging affect these numbers. Do not substitute them for the Ubuntu/Mininet benchmark.', '',
             '| Mode | Samples | Connect median ms | Steady echo median ms | Application goodput median Mbps |',
             '|---|---:|---:|---:|---:|']
    for mode in ('baseline','firewall'):
        rows = [r for r in results if r['mode']==mode]
        medians = [statistics.median(r[key] for r in rows) for key in ('connect_ms','steady_median_ms','application_mbps')]
        lines.append(f'| {mode} | {len(rows)} | '+' | '.join(f'{v:.3f}' for v in medians)+' |')
    (output/'LOCAL-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'Local-only benchmark saved: {output / "LOCAL-summary.md"}',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=['demo','serve','bench'],default='demo')
    parser.add_argument('--mode',choices=['firewall','baseline'],default='firewall')
    parser.add_argument('--base-port',type=int,default=None,help='serve default 15000; demo uses free ports')
    parser.add_argument('--samples',type=int,default=10)
    parser.add_argument('--tag',default='local-'+time.strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    if not args.tag.replace('-','').replace('_','').isalnum():
        parser.error('tag must contain only letters, digits, hyphens or underscores')
    if args.samples<1 or (args.base_port is not None and not 0<=args.base_port<=65531):
        parser.error('samples must be positive; base-port must be 0..65531')
    if args.action=='demo' and args.mode!='firewall':
        parser.error('demo tests firewall behavior; use serve for interactive baseline')
    output = ROOT/'results'/args.tag
    if args.action=='bench':
        output.mkdir(parents=True,exist_ok=False)
        benchmark(output,args.samples)
        return
    base = args.base_port if args.base_port is not None else (15000 if args.action=='serve' else 0)
    with LocalLab(output,mode=args.mode,base_port=base) as lab:
        if args.action=='demo':
            demo(lab)
        else:
            print('Use client.py in another terminal. Ctrl+C stops the entire lab.',flush=True)
            try:
                while True:
                    time.sleep(.5)
            except KeyboardInterrupt:
                print('\nStopping local lab...',flush=True)

if __name__=='__main__':
    try:
        main()
    except (OSError,AssertionError) as exc:
        raise SystemExit(f'Local lab failed: {exc}') from exc
