"""One JSON object per TCP connection; bounded timeouts and explicit fallback."""
import datetime
import json
import socket
import sys
import time
import uuid

MAX_LINE = 131072

def event(component, kind, **fields):
    return dict(event_id=uuid.uuid4().hex,
                time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                monotonic_ns=time.monotonic_ns(), component=component, kind=kind, **fields)

def send_event(record, host, port=7000, socket_module=socket):
    payload = (json.dumps(record, sort_keys=True) + '\n').encode()
    try:
        with socket_module.create_connection((host, port), timeout=0.3) as sock:
            sock.sendall(payload)
            with sock.makefile('rb') as reply:
                if reply.readline(16) != b'OK\n':
                    raise OSError('logger did not acknowledge persistence')
        return True
    except OSError as exc:
        print(json.dumps({'kind': 'LOGGER_UNAVAILABLE', 'error': str(exc),
                          'original': record}), file=sys.stderr, flush=True)
        return False
