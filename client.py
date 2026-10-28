"""Each invocation creates one TCP connection; benchmark samples use fresh ones."""
import argparse
import json
import socket
import statistics
import time

def request(host, port=5000, count=1, size=64, timeout=1):
    start = time.monotonic_ns()
    result = dict(start_ns=start, host=host, port=port, messages=count, payload_bytes=size, success=False)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            connected = time.monotonic_ns()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            payload = b'x' * size + b'\n'
            latencies = []
            with sock.makefile('rb') as incoming:
                for _ in range(count):
                    t = time.perf_counter()
                    sock.sendall(payload)
                    if incoming.readline(size + 2) != payload:
                        raise OSError('echo mismatch or premature EOF')
                    latencies.append((time.perf_counter() - t) * 1000)
            elapsed = (time.monotonic_ns() - connected) / 1e9
            result.update(success=True, connect_ms=(connected-start)/1e6,
                          first_echo_ms=latencies[0], median_echo_ms=statistics.median(latencies),
                          p95_echo_ms=sorted(latencies)[max(0, __import__('math').ceil(.95*len(latencies))-1)],
                          application_mbps=count*size*8/elapsed/1e6,
                          steady_median_ms=statistics.median(latencies[1:]) if count > 1 else None)
    except OSError as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
    result['end_ns'] = time.monotonic_ns()
    result['elapsed_ms'] = (result['end_ns'] - start)/1e6
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='10.0.0.3')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--size', type=int, default=64)
    parser.add_argument('--timeout', type=float, default=1)
    args = parser.parse_args()
    if not (1 <= args.count <= 100000 and 1 <= args.size <= 65536 and args.timeout > 0):
        parser.error('count 1..100000, size 1..65536, timeout > 0 required')
    result = request(args.host, args.port, args.count, args.size, args.timeout)
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result['success'] else 1)
