"""Pure decision logic: no Mininet or controller imports, so it is easy to test."""
from collections import defaultdict
import time

CLIENTS = {'10.0.0.1': 1, '10.0.0.2': 2}
PORTS = {**CLIENTS, '10.0.0.3': 3, '10.0.0.4': 4}
SERVER = '10.0.0.3'
LOGGER = '10.0.0.4'

class Policy:
    def __init__(self, threshold=3, window=10, block_seconds=10, clock=time.monotonic):
        self.threshold, self.window, self.block_seconds = threshold, window, block_seconds
        self.clock = clock
        self.attempts = defaultdict(dict)
        self.blocked = {}

    def recover(self, source):
        self.blocked.pop(source, None)
        self.attempts.pop(source, None)

    def decide(self, source, destination, source_port, destination_port, syn, ack):
        now = self.clock()
        if source in self.blocked:
            if now < self.blocked[source]:
                return 'BLOCKED', 0
            self.recover(source)
        allowed = ((source in CLIENTS and destination == SERVER and destination_port == 5000)
                   or (source == SERVER and destination == LOGGER and destination_port == 7000))
        if allowed:
            return 'ALLOW', 0
        # Only initial SYNs count. Retransmissions of the same 4-tuple within
        # the window count once; a new connect() normally uses a new source port.
        recent = self.attempts[source]
        for key, timestamp in list(recent.items()):
            if now - timestamp >= self.window:
                del recent[key]
        if syn and not ack:
            recent.setdefault((destination, source_port, destination_port), now)
        count = len(recent)
        if count >= self.threshold:
            self.blocked[source] = now + self.block_seconds
            return 'BLOCK', count
        return 'DENY', count
