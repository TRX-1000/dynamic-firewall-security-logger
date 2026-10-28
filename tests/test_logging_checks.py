import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logging_checks import complete_records, delivery_state, wait_for_delivery

class DeliveryTests(unittest.TestCase):
    def test_missing_controller_event_prevents_success(self):
        r={'event_id':'one','component':'controller','kind':'ALLOW'}
        self.assertFalse(delivery_state([r], [], set())[0])
        self.assertTrue(delivery_state([r], [r], set())[0])

    def test_prior_controller_events_do_not_require_replay(self):
        old={'event_id':'old','component':'controller','kind':'ALLOW'}
        new=dict(old,event_id='new')
        self.assertTrue(delivery_state([old,new], [new], {'old'})[0])

    def test_disconnect_must_be_persisted_before_shutdown(self):
        r={'event_id':'one','component':'controller','kind':'ALLOW'}
        connect={'event_id':'two','component':'server','kind':'CONNECT','peer':'client:123'}
        disconnect=dict(connect,event_id='three',kind='DISCONNECT')
        self.assertFalse(delivery_state([r], [r,connect], set())[0])
        self.assertTrue(delivery_state([r], [r,connect,disconnect], set())[0])

    def test_partial_record_is_not_read_as_complete(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'log'
            p.write_text('{"event_id":"complete"}\n{"event_id":')
            self.assertEqual(complete_records(p), [{'event_id':'complete'}])

    def test_timeout_fails_instead_of_claiming_success(self):
        with tempfile.TemporaryDirectory() as d:
            local=Path(d)/'local'; central=Path(d)/'central'
            local.write_text(json.dumps({'event_id':'one','component':'controller','kind':'ALLOW'})+'\n')
            central.write_text('')
            with self.assertRaisesRegex(AssertionError, 'did not drain'):
                wait_for_delivery(local,central,set(),timeout=.1,quiet=.05)
            central.write_text(local.read_text())
            self.assertEqual(wait_for_delivery(local,central,set(),timeout=.5,quiet=.05)['status'],'passed')

if __name__ == '__main__':
    unittest.main()
