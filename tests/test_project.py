import concurrent.futures
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import request
from events import event, send_event
from logger_server import Logger
from policy import Policy
from server import Server, Handler

class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.policy = Policy(clock=lambda: self.now)

    def attempt(self, sport=40000, dport=9999, src='10.0.0.2', dst='10.0.0.3', syn=True, ack=False):
        return self.policy.decide(src, dst, sport, dport, syn, ack)

    def test_allow_requires_correct_source_destination_and_port(self):
        self.assertEqual(self.attempt(dport=5000)[0], 'ALLOW')
        self.assertEqual(self.attempt(dst='10.0.0.4', dport=5000)[0], 'DENY')
        self.assertEqual(self.attempt(src='10.0.0.4', dport=5000)[0], 'DENY')
        self.assertEqual(self.attempt(src='10.0.0.3', dst='10.0.0.4', dport=7000)[0], 'ALLOW')

    def test_retransmissions_and_non_syn_do_not_inflate_count(self):
        for _ in range(8):
            self.assertEqual(self.attempt(), ('DENY', 1))
        self.assertEqual(self.attempt(sport=40001, syn=False), ('DENY', 1))
        self.assertEqual(self.attempt(sport=40002, ack=True), ('DENY', 1))

    def test_threshold_isolation_and_recovery(self):
        self.assertEqual(self.attempt(sport=40000), ('DENY', 1))
        self.assertEqual(self.attempt(sport=40001), ('DENY', 2))
        self.assertEqual(self.attempt(sport=40002), ('BLOCK', 3))
        self.assertEqual(self.attempt(dport=5000)[0], 'BLOCKED')
        self.assertEqual(self.attempt(src='10.0.0.1', dport=5000)[0], 'ALLOW')
        self.now += 10
        self.assertEqual(self.attempt(dport=5000)[0], 'ALLOW')
        self.assertEqual(self.attempt(), ('DENY', 1))

    def test_window_expiration_and_explicit_flow_recovery(self):
        self.attempt()
        self.now += 10
        self.assertEqual(self.attempt(sport=40001), ('DENY', 1))
        self.attempt(sport=40002)
        self.attempt(sport=40003)
        self.policy.recover('10.0.0.2')
        self.assertEqual(self.attempt(dport=5000)[0], 'ALLOW')

class SocketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'events.jsonl'
        self.logger = Logger(('127.0.0.1',0), self.path)
        self.app = Server(('127.0.0.1',0), Handler)
        self.app.logger_host = '127.0.0.1'
        self.app.logger_port = self.logger.server_address[1]
        self.threads = []
        for service in (self.logger, self.app):
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for service in (self.app,self.logger):
            service.shutdown()
            service.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.temp.cleanup()

    def test_concurrent_clients_and_central_logs(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(request, '127.0.0.1', self.app.server_address[1], 20, 4096, 3) for _ in range(8)]
            self.assertTrue(all(f.result()['success'] for f in futures))
        events = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len([e for e in events if e['kind']=='CONNECT']), 8)
        self.assertEqual(len({e['event_id'] for e in events}), len(events))

    def test_split_and_coalesced_tcp_frames(self):
        with socket.create_connection(self.app.server_address,timeout=3) as sock:
            sock.sendall(b'hel')
            sock.sendall(b'lo\nsecond\n')
            with sock.makefile('rb') as incoming:
                self.assertEqual(incoming.readline(), b'hello\n')
                self.assertEqual(incoming.readline(), b'second\n')

    def test_logger_ack_means_record_is_persisted(self):
        record = event('test', 'TEST_EVENT', value=7)
        self.assertTrue(send_event(record, '127.0.0.1', self.logger.server_address[1]))
        self.assertEqual(json.loads(self.path.read_text())['value'], 7)

    def test_logger_rejects_malformed_json_then_accepts_valid_record(self):
        with socket.create_connection(self.logger.server_address,timeout=3) as sock:
            sock.sendall(b'not json\n')
            self.assertEqual(sock.recv(16), b'')
        self.assertTrue(send_event(event('test','AFTER_BAD_INPUT'), '127.0.0.1', self.logger.server_address[1]))

    def test_logger_outage_does_not_break_echo(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            self.app.logger_port = reserved.getsockname()[1]
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                result = request('127.0.0.1', self.app.server_address[1], timeout=2)
                self.assertTrue(result['success'])
                self.assertIn('LOGGER_UNAVAILABLE', errors.getvalue())

    def test_client_reports_closed_port(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0))
            result = request('127.0.0.1',reserved.getsockname()[1],timeout=.1)
            self.assertFalse(result['success'])
            self.assertIn('error',result)

if __name__ == '__main__':
    unittest.main()
