"""Threaded centralized TCP logger with JSONL persistence and acknowledgement."""
import argparse
import json
import os
from pathlib import Path
import socketserver
import threading
from events import MAX_LINE

class Logger(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, output):
        self.output = Path(output)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        super().__init__(address, Handler)

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(2)
        try:
            line = self.rfile.readline(MAX_LINE + 1)
            if len(line) > MAX_LINE or not line.endswith(b'\n'):
                return
            record = json.loads(line)
            if not isinstance(record, dict) or not {'event_id', 'kind', 'component'} <= record.keys():
                return
            record['logger_peer'] = self.client_address[0]
            with self.server.lock:
                with self.server.output.open('a') as output:
                    output.write(json.dumps(record, sort_keys=True) + '\n')
                    output.flush()
                    os.fsync(output.fileno())
            self.wfile.write(b'OK\n')
        except (OSError, ValueError):
            return

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=7000)
    parser.add_argument('--output', default='results/security.jsonl')
    args = parser.parse_args()
    with Logger((args.host, args.port), args.output) as server:
        print(f'Logger listening on {server.server_address}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
