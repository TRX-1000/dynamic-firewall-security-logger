"""Real OS-Ken process + simulated OpenFlow 1.3 peer. Not an OVS substitute.
Run with the controller virtualenv's Python. No root or Mininet required.
"""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from logger_server import Logger

def header(kind, body=b'', xid=1):
    return struct.pack('!BBHI', 4, kind, 8+len(body), xid)+body

def exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size-len(data))
        if not chunk:
            raise RuntimeError('controller closed the connection')
        data += chunk
    return data

def pump(sock, duration=.3):
    messages = []
    until = time.monotonic()+duration
    while time.monotonic() < until:
        sock.settimeout(max(.001,until-time.monotonic()))
        try:
            raw = exact(sock, 8)
        except socket.timeout:
            break
        version, kind, length, xid = struct.unpack('!BBHI',raw)
        body = exact(sock,length-8)
        messages.append((kind,body))
        if kind == 5:  # FeaturesRequest
            sock.sendall(header(6,struct.pack('!QIBB2xII',1,256,1,0,0,0),xid))
        elif kind == 18:  # multipart request: empty port description response
            sock.sendall(header(19,body[:2]+b'\x00'*6,xid))
        elif kind == 2:
            sock.sendall(header(3,body,xid))
        elif kind == 20:
            sock.sendall(header(21,b'',xid))
    return messages

def inject(sock, source, destination, sport, dport, ingress):
    eth = b'\x00\x00\x00\x00\x00\x03'+bytes([0,0,0,0,0,ingress])+b'\x08\x00'
    ip = struct.pack('!BBHHHBBH4s4s',0x45,0,40,1,0,64,6,0,
                     socket.inet_aton(source),socket.inet_aton(destination))
    tcp = struct.pack('!HHIIBBHHH',sport,dport,1,0,0x50,2,65535,0,0)
    frame = eth+ip+tcp
    match = struct.pack('!HHII',1,12,0x80000004,ingress)+b'\x00'*4
    body = struct.pack('!IHBBQ',0xffffffff,len(frame),0,0,0)+match+b'\x00'*2+frame
    sock.sendall(header(10,body))  # OFPT_PACKET_IN = 10
    return pump(sock)

def flows(messages, priority):
    return [body for kind,body in messages if kind==14 and struct.unpack_from('!H',body,22)[0]==priority]

def drop_has_no_actions(flow):
    match_length = struct.unpack_from('!H',flow,42)[0]
    instructions = flow[40 + ((match_length+7)//8)*8:]
    return instructions == struct.pack('!HH4x',4,8)

def main():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        logger = Logger(('127.0.0.1',0),output/'central.jsonl')
        thread = threading.Thread(target=logger.serve_forever,daemon=True)
        thread.start()
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0))
            port = reservation.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(ROOT), EVENTLET_NO_GREENDNS='yes',
                   FW_MODE='firewall', FW_LOGGER='127.0.0.1',
                   FW_LOGGER_PORT=str(logger.server_address[1]), FW_LOCAL_LOG=str(output/'controller.jsonl'))
        with (output/'process.log').open('w+') as log:
            process = subprocess.Popen([str(Path(sys.executable).parent/'osken-manager'),
                '--ofp-listen-host','127.0.0.1','--ofp-tcp-listen-port',str(port),str(ROOT/'controller.py')],
                env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+10
                while True:
                    try:
                        peer = socket.create_connection(('127.0.0.1',port),timeout=.2)
                        break
                    except OSError:
                        if process.poll() is not None or time.monotonic()>deadline:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        time.sleep(.1)
                with peer:
                    peer.sendall(header(0))
                    initial = pump(peer,1)
                    assert flows(initial,0), 'missing table-miss flow'
                    allowed = inject(peer,'10.0.0.1','10.0.0.3',41000,5000,1)
                    assert len(flows(allowed,100))==2, 'missing forward/reverse allows'
                    assert any(kind==13 for kind,_ in allowed), 'missing PacketOut'
                    for sport in (42000,42001):
                        denied = inject(peer,'10.0.0.2','10.0.0.3',sport,9999,2)
                        assert len(flows(denied,200))==1
                        assert drop_has_no_actions(flows(denied,200)[0])
                        assert not any(kind==13 for kind,_ in denied)
                    blocked = inject(peer,'10.0.0.2','10.0.0.3',42002,9999,2)
                    block = flows(blocked,300)[0]
                    assert struct.unpack_from('!H',block,20)[0]==10, 'wrong hard timeout'
                    assert drop_has_no_actions(block)
                    assert not flows(inject(peer,'10.0.0.2','10.0.0.3',42003,5000,2),100)
                    # Simulated switch expiry: validates event handling, NOT real timer behavior.
                    cookie = struct.unpack_from('!Q',block)[0]
                    removal = struct.pack('!QHBBIIHHQQ',cookie,300,1,0,10,0,0,10,4,240)+block[40:]
                    # FlowRemoved ends with its match, not FlowMod instructions.
                    match_len = struct.unpack_from('!H',block,42)[0]
                    removal = removal[:40+((match_len+7)//8)*8]
                    peer.sendall(header(11,removal))
                    pump(peer)
                    recovered = inject(peer,'10.0.0.2','10.0.0.3',42004,5000,2)
                    assert flows(recovered,100), 'policy failed to recover after FlowRemoved'
                    pump(peer,.5)
                central = [json.loads(line) for line in (output/'central.jsonl').read_text().splitlines()]
                kinds = {r['kind'] for r in central}
                assert {'ALLOW','DENY','BLOCK_REQUEST','BLOCK_CONFIRMED','RECOVER'} <= kinds, kinds
                assert 'OPENFLOW_ERROR' not in kinds
                log.seek(0)
                assert 'Traceback' not in log.read(), 'controller raised an exception'
                print('PASS: real OS-Ken handshake, allow/reverse/deny/block FlowMods, PacketOut, barrier, simulated recovery and central logs')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                logger.shutdown()
                logger.server_close()
                thread.join(timeout=2)

if __name__ == '__main__':
    main()
