#!/usr/bin/env python3
"""Run with system Python as root; Mininet is installed through Ubuntu apt."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import time
from logging_checks import wait_for_delivery, complete_records
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController, Node
from mininet.cli import CLI
from mininet.log import setLogLevel

ROOT = Path(__file__).resolve().parent

def build():
    net = Mininet(controller=None, switch=OVSSwitch, autoSetMacs=True)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
    switch = net.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13', failMode='secure')
    for number in range(1, 5):
        host = net.addHost(f'h{number}', ip=f'10.0.0.{number}/24')
        net.addLink(host, switch, port2=number)
    # Dedicated management link: root-namespace controller can reach h4 without
    # routing its own log traffic through the switch it controls.
    management = Node('mgmt', inNamespace=False)
    link = net.addLink(management, net.get('h4'))
    management.setIP('192.168.100.1/30', intf=link.intf1)
    net.get('h4').setIP('192.168.100.2/30', intf=link.intf2)
    return net, management

def records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def probe(host, port=5000, count=1, size=64, timeout=.5):
    command = ['python3', str(ROOT/'client.py'), '--port', str(port), '--count', str(count),
               '--size', str(size), '--timeout', str(timeout)]
    result = host.popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = result.communicate(timeout=max(10, count*timeout + 2))
    try:
        return json.loads(stdout)
    except ValueError as exc:
        raise RuntimeError(f'Client failed: {stdout!r} {stderr!r}') from exc

def await_events(path, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = records(path)
        if predicate(events):
            return events
        time.sleep(.1)
    raise AssertionError(f'Expected controller events missing from {path}')

def demo(net, output):
    checks = []
    def check(label, host='h2', expected=True, **kwargs):
        result = probe(net.get(host), **kwargs)
        result.update(check=label, expected=expected)
        checks.append(result)
        (output/'demo.json').write_text(json.dumps(checks, indent=2))
        print(label, 'PASS' if result['success'] == expected else 'FAIL', flush=True)
        assert result['success'] == expected, result
        if not expected:
            assert result['error'].startswith('TimeoutError:'), result
        return result
    local = net.get('h3').cmd('python3 ' + shlex.quote(str(ROOT/'client.py')) + ' --host 127.0.0.1 --port 9999')
    assert json.loads(local)['success'], 'Forbidden-port service is not healthy'
    concurrent = [net.get(host).popen(['python3', str(ROOT/'client.py'), '--count', '20', '--timeout', '2'],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for host in ('h1','h2')]
    for process in concurrent:
        stdout, stderr = process.communicate(timeout=10)
        assert json.loads(stdout)['success'], (stdout, stderr)
    print('Concurrent clients PASS', flush=True)
    check('client 1 allowed', 'h1')
    check('client 2 allowed')
    await_events(output/'security.jsonl', lambda es: any(e.get('mode') == 'firewall' for e in es))
    for number in range(3):
        check(f'unauthorized attempt {number+1}', port=9999, expected=False)
    events = await_events(output/'security.jsonl', lambda es: any(e['kind']=='BLOCK_CONFIRMED' for e in es))
    check('blocked client cannot use allowed port', expected=False)
    check('other client unaffected', 'h1')
    block = next(e for e in events if e['kind']=='BLOCK_REQUEST')
    last_failure = checks[-2]['end_ns']
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = probe(net.get('h2'), timeout=.25)
        checks.append(dict(result, check='recovery probe'))
        if result['success']:
            (output/'recovery.json').write_text(json.dumps({
                'block_decision_ns': block['decision_ns'],
                'last_failed_probe_end_ns': last_failure,
                'first_success_end_ns': result['end_ns'],
                'observed_recovery_ms': (result['end_ns']-block['decision_ns'])/1e6,
                'probe_interval_note': '250 ms sleep + up to 250 ms connection timeout; observation includes scheduling/echo'}, indent=2))
            break
        last_failure = result['end_ns']
        time.sleep(.25)
    else:
        raise AssertionError('Client failed to recover within 15 seconds')
    (output/'demo.json').write_text(json.dumps(checks, indent=2))
    await_events(output/'security.jsonl', lambda es: any(e['kind']=='RECOVER' for e in es))
    # Verify policy persists after recovery, rather than turning the firewall off.
    check('forbidden port remains denied after recovery', port=9999, expected=False)
    print('DEMO PASSED: allow, deny, threshold block, isolation, recovery, persistent policy', flush=True)

def benchmark(net, output, mode, samples):
    if mode == 'baseline':
        assert probe(net.get('h2'), port=9999, timeout=2)['success'], 'Baseline must reach the forbidden service'
    # Discard warm-up; cold TCP connections remain new for every measured sample.
    warm = probe(net.get('h1'), count=10, timeout=2)
    assert warm['success'], warm
    await_events(output/'security.jsonl', lambda es: any(e.get('mode')==mode for e in es))
    with (output/'benchmark.jsonl').open('w') as stream:
        for i in range(samples):
            result = probe(net.get('h1'), count=200, size=4096, timeout=2)
            result.update(mode=mode, sample=i)
            stream.write(json.dumps(result)+'\n')
            stream.flush()
            assert result['success'], result
    print(f'{samples} {mode} samples saved in {output}', flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=['cli','demo','bench'], default='cli')
    parser.add_argument('--mode', choices=['firewall','baseline'], default='firewall')
    parser.add_argument('--tag', default=time.strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--controller-log', default='results/controller.jsonl')
    args = parser.parse_args()
    if not args.tag.replace('-', '').replace('_','').isalnum() or args.samples < 1:
        parser.error('Use a simple alphanumeric tag and positive samples')
    output = ROOT/'results'/args.tag
    output.mkdir(parents=True, exist_ok=False)
    controller_log = Path(args.controller_log)
    if not controller_log.is_absolute():
        controller_log = ROOT/controller_log
    prior_ids = {e['event_id'] for e in complete_records(controller_log)}
    net, management = build()
    processes, handles = [], []
    try:
        # Configure host namespaces before opening the logger. Start the switch
        # only once the logger is listening, so SWITCH_READY can be delivered.
        net.build()
        # Start logger before either application server.
        jobs = [('h4', 'logger', ['logger_server.py','--output',str(output/'security.jsonl')]),
                ('h3', 'server', ['server.py']),
                ('h3', 'forbidden-service', ['server.py','--port','9999'])]
        for host, name, command in jobs:
            log = (output/f'{name}.log').open('w')
            handles.append(log)
            process = net.get(host).popen(['python3', '-u', str(ROOT/command[0]), *command[1:]], stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            deadline = time.monotonic()+5
            while 'listening' not in (output/f'{name}.log').read_text():
                assert process.poll() is None, f'{name} exited; inspect its log'
                assert time.monotonic() < deadline, f'{name} startup timeout'
                time.sleep(.1)
            if name == 'logger':
                net.start()
                assert net.waitConnected(timeout=10), 'Controller unavailable on 127.0.0.1:6653'
                await_events(output/'security.jsonl', lambda es: any(e['kind']=='SWITCH_READY' for e in es))
        assert net.pingAll(timeout='1') == 0, 'Initial connectivity check failed'
        print(f'Logs and measurements: {output}', flush=True)
        if args.action == 'demo':
            assert args.mode == 'firewall', 'Demo requires firewall controller mode'
            demo(net, output)
        elif args.action == 'bench':
            benchmark(net, output, args.mode, args.samples)
        else:
            print('Services already running: h3:5000, h3:9999, h4:7000')
            CLI(net)
        # Keep services alive until all observed controller events and server
        # disconnect records reach the central log. A timeout fails the run;
        # it is never reported as successful logging.
        delivery = wait_for_delivery(controller_log, output/'security.jsonl', prior_ids)
        (output/'logging-validation.json').write_text(json.dumps(delivery, indent=2))
        print('LOG DELIVERY PASSED:', delivery, flush=True)
        events = records(output/'security.jsonl')
        assert not any(e['kind']=='OPENFLOW_ERROR' for e in events), 'OpenFlow error; inspect logs'
    finally:
        for process in list(reversed(processes)):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
        net.stop()
        management.terminate()

if __name__ == '__main__':
    setLogLevel('info')
    main()
