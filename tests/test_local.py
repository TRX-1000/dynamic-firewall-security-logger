"""Portable proxy integration tests; no OS-Ken or Mininet imports."""
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_lab import LocalLab

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name)/'run'
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()

    def tearDown(self):
        self.quiet.__exit__(None,None,None)
        self.directory.cleanup()

    def test_real_proxy_block_isolation_recovery_and_logging(self):
        with LocalLab(self.output,block_seconds=.6) as lab:
            self.assertTrue(lab.probe(timeout=1)['success'])
            for _ in range(3):
                denied = lab.probe(port=9999,timeout=.07)
                self.assertFalse(denied['success'])
                self.assertTrue(denied['error'].startswith('TimeoutError:'))
            self.assertFalse(lab.probe(timeout=.07)['success'])
            self.assertTrue(lab.probe(host='h1',timeout=1)['success'])
            deadline=time.monotonic()+2
            while lab.fw.is_blocked('10.0.0.2') and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue(lab.probe(timeout=1)['success'])
            self.assertFalse(lab.probe(port=9999,timeout=.07)['success'])
        records=[json.loads(line) for line in (self.output/'security.jsonl').read_text().splitlines()]
        kinds={r['kind'] for r in records if r['component']=='local-proxy'}
        self.assertTrue({'ALLOW','DENY','BLOCK','BLOCKED','RECOVER'}<=kinds)
        self.assertNotIn('PROXY_ERROR',kinds)

    def test_baseline_allows_forbidden_service_without_blocking(self):
        with LocalLab(self.output,mode='baseline') as lab:
            for _ in range(4):
                self.assertTrue(lab.probe(port=9999,timeout=1)['success'])
            self.assertFalse(lab.fw.is_blocked('10.0.0.2'))

    def test_proxy_preserves_split_and_coalesced_frames(self):
        with LocalLab(self.output) as lab:
            with socket.create_connection(('127.0.0.1',lab.ports[('h1',5000)]),timeout=1) as sock:
                sock.sendall(b'hel')
                sock.sendall(b'lo\nsecond\n')
                with sock.makefile('rb') as stream:
                    self.assertEqual(stream.readline(),b'hello\n')
                    self.assertEqual(stream.readline(),b'second\n')

    def test_block_also_applies_to_already_open_connection(self):
        with LocalLab(self.output,block_seconds=.6) as lab:
            with socket.create_connection(('127.0.0.1',lab.ports[('h2',5000)]),timeout=1) as sock:
                sock.sendall(b'before\n')
                self.assertEqual(sock.recv(100),b'before\n')
                for _ in range(3):
                    self.assertFalse(lab.probe(port=9999,timeout=.05)['success'])
                sock.settimeout(.07)
                sock.sendall(b'during\n')
                with self.assertRaises(socket.timeout):
                    sock.recv(100)
                deadline=time.monotonic()+2
                while lab.fw.is_blocked('10.0.0.2') and time.monotonic()<deadline:
                    time.sleep(.02)
                sock.settimeout(1)
                sock.sendall(b'after\n')
                self.assertEqual(sock.recv(100),b'after\n')

    def test_port_conflict_fails_cleanly(self):
        # Hold the first expected listener port without listening.
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0))
            port=reserved.getsockname()[1]
            with self.assertRaises(OSError):
                with LocalLab(self.output,base_port=port-1):
                    pass

if __name__=='__main__':
    unittest.main()
