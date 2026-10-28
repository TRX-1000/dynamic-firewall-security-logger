"""Check central persistence before Mininet stops the logging service."""
from collections import Counter
import json
import time


def complete_records(path):
    if not path.exists():
        return []
    # Producers can be in the middle of appending the last record.
    data = path.read_text()
    return [json.loads(line) for line in data.splitlines(keepends=True)
            if line.endswith('\n') and line.strip()]


def delivery_state(local, central, prior_ids):
    expected = {r['event_id'] for r in local} - prior_ids
    persisted = {r['event_id'] for r in central}
    connected = Counter(r['peer'] for r in central
                        if r['component'] == 'server' and r['kind'] == 'CONNECT')
    disconnected = Counter(r['peer'] for r in central
                           if r['component'] == 'server' and r['kind'] == 'DISCONNECT')
    missing = sorted(expected - persisted)
    pending = dict(connected - disconnected)
    ready = bool(expected) and not missing and not pending
    return ready, {'controller_events': len(expected), 'missing_event_ids': missing,
                   'pending_disconnects': pending, 'central_records': len(central)}


def wait_for_delivery(local_path, central_path, prior_ids, timeout=10, quiet=1):
    deadline = time.monotonic() + timeout
    stable_since = None
    previous = None
    state = {}
    while time.monotonic() < deadline:
        local = complete_records(local_path)
        central = complete_records(central_path)
        ready, state = delivery_state(local, central, prior_ids)
        signature = (len(local), len(central))
        now = time.monotonic()
        if ready:
            if signature != previous or stable_since is None:
                stable_since = now
            elif now - stable_since >= quiet:
                return dict(state, quiet_seconds=quiet, status='passed')
        else:
            stable_since = None
        previous = signature
        time.sleep(.05)
    raise AssertionError(f'Central log did not drain before shutdown: {state}')
