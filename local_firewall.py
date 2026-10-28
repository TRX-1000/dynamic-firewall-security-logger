"""Portable socket proxy adapter for policy.py. This is NOT an OpenFlow switch.
All sockets bind to loopback. Listener identity represents a logical Mininet host.
"""
import json
from pathlib import Path
import queue
import select
import socket
import socketserver
import threading
import time
from events import event, send_event
from policy import Policy

class LocalFirewall:
    def __init__(self, output, logger_port, mode='firewall', block_seconds=10):
        self.policy = Policy(block_seconds=block_seconds)
        self.mode = mode
        self.logger_port = logger_port
        self.path = Path(output)/'local-firewall.jsonl'
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.queue = queue.Queue(256)
        self.records = []
        self.block_started = {}
        self.worker = threading.Thread(target=self.deliver, daemon=True)
        self.timer = threading.Thread(target=self.recovery_timer, daemon=True)
        self.worker.start()
        self.timer.start()

    def emit(self, kind, **fields):
        record = event('local-proxy', kind, environment='localhost-proxy', mode=self.mode, **fields)
        with self.lock:
            self.records.append(record)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record)+'\n')
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            # The durable local copy remains available; no automatic replay.
            print('Logger queue full; event retained locally', flush=True)

    def deliver(self):
        while True:
            record = self.queue.get()
            try:
                if record is None:
                    return
                send_event(record, '127.0.0.1', self.logger_port)
            finally:
                self.queue.task_done()

    def expire(self):
        # Caller owns the lock. Expire before Policy.decide to preserve RECOVER.
        now = time.monotonic()
        for source, deadline in list(self.policy.blocked.items()):
            if now >= deadline:
                started = self.block_started.pop(source, now)
                self.policy.recover(source)
                self.emit('RECOVER', src=source, observed_block_ms=(now-started)*1000,
                          mechanism='Python monotonic timer; not an OVS flow expiry')

    def recovery_timer(self):
        while not self.stopped.wait(.05):
            with self.lock:
                self.expire()

    def decide(self, source, source_port, destination_port):
        with self.lock:
            self.expire()
            decision, count = ('ALLOW', 0) if self.mode == 'baseline' else self.policy.decide(
                source, '10.0.0.3', source_port, destination_port, True, False)
            if decision == 'BLOCK':
                self.block_started[source] = time.monotonic()
            self.emit(decision, src=source, dst='10.0.0.3', sport=source_port,
                      dport=destination_port, count=count,
                      block_seconds=self.policy.block_seconds if decision == 'BLOCK' else None)
            return decision

    def is_blocked(self, source):
        with self.lock:
            self.expire()
            return source in self.policy.blocked

    def close(self):
        self.stopped.set()
        self.timer.join(timeout=2)
        self.queue.join()
        self.queue.put(None)
        self.worker.join(timeout=2)

class Proxy(socketserver.ThreadingTCPServer):
    # Windows should fail if another process already owns the port.
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True
    request_queue_size = 64

    def __init__(self, port, source, destination_port, backend_port, firewall):
        self.source, self.destination_port = source, destination_port
        self.backend_port, self.firewall = backend_port, firewall
        super().__init__(('127.0.0.1', port), ProxyHandler)

class ProxyHandler(socketserver.BaseRequestHandler):
    def silence(self):
        # TCP handshake already succeeded at this proxy. Discard application data
        # until the client times out/closes; this does NOT simulate a SYN drop.
        deadline = time.monotonic()+5
        while not self.server.firewall.stopped.is_set() and time.monotonic()<deadline:
            ready, _, _ = select.select([self.request], [], [], .05)
            if ready and not self.request.recv(65536):
                return

    def handle(self):
        fw = self.server.firewall
        if fw.stopped.is_set():
            return
        self.request.settimeout(.5)
        try:
            decision = fw.decide(self.server.source, self.client_address[1], self.server.destination_port)
            if decision != 'ALLOW':
                self.silence()
                return
            with socket.create_connection(('127.0.0.1', self.server.backend_port), timeout=1) as upstream:
                upstream.settimeout(.5)
                upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                while not fw.stopped.is_set():
                    ready, _, _ = select.select([self.request, upstream], [], [], .05)
                    for incoming in ready:
                        data = incoming.recv(65536)
                        if not data:
                            return
                        # Also suppress already-open sessions during a source block.
                        if fw.is_blocked(self.server.source):
                            continue
                        outgoing = upstream if incoming is self.request else self.request
                        outgoing.sendall(data)
        except OSError as exc:
            if not fw.stopped.is_set():
                fw.emit('PROXY_ERROR', src=self.server.source, error=str(exc))
