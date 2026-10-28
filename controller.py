"""Single-switch OpenFlow 1.3 firewall for topology.py (explicit port/IP binding)."""
import json
import os
from pathlib import Path
import time
from eventlet.green import socket
from eventlet.queue import Full
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ipv4, tcp
from os_ken.ofproto import ofproto_v1_3
from events import event, send_event
from policy import Policy, PORTS

class Firewall(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = os.environ.get('FW_MODE', 'firewall')
        if self.mode not in ('firewall', 'baseline'):
            raise ValueError('FW_MODE must be firewall or baseline')
        self.policy = Policy()
        self.pending = {}
        self.blocks = {}
        self.cookie = 100
        self.log_path = Path(os.environ.get('FW_LOCAL_LOG', 'results/controller.jsonl'))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue = hub.Queue(256)
        self.worker = hub.spawn(self.deliver)

    def emit(self, kind, **fields):
        record = event('controller', kind, mode=self.mode, **fields)
        # Always retain a local copy even if the central logger is unavailable.
        with self.log_path.open('a') as output:
            output.write(json.dumps(record, sort_keys=True) + '\n')
        try:
            self.queue.put_nowait(record)
        except Full:
            self.logger.warning('Logger queue full; event retained in %s', self.log_path)

    def deliver(self):
        while True:
            record = self.queue.get()
            send_event(record, os.environ.get('FW_LOGGER', '192.168.100.2'),
                       port=int(os.environ.get('FW_LOGGER_PORT', '7000')), socket_module=socket)

    def flow(self, dp, priority, match, actions, hard=0, idle=0, cookie=0, notify=False):
        p, of = dp.ofproto_parser, dp.ofproto
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=priority, match=match,
                    instructions=[p.OFPInstructionActions(of.OFPIT_APPLY_ACTIONS, actions)],
                    hard_timeout=hard, idle_timeout=idle, cookie=cookie,
                    flags=of.OFPFF_SEND_FLOW_REM if notify else 0))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features(self, ev):
        dp = ev.msg.datapath
        p, of = dp.ofproto_parser, dp.ofproto
        if dp.id != 1:
            self.logger.error('Only datapath 1 is supported')
            return
        self.policy = Policy()
        self.blocks.clear()
        self.pending.clear()
        dp.send_msg(p.OFPFlowMod(datapath=dp, command=of.OFPFC_DELETE,
                    out_port=of.OFPP_ANY, out_group=of.OFPG_ANY, match=p.OFPMatch()))
        self.flow(dp, 0, p.OFPMatch(), [p.OFPActionOutput(of.OFPP_CONTROLLER, of.OFPCML_NO_BUFFER)])
        # ARP is permitted for address resolution. IPv6/non-IP get default drops.
        self.flow(dp, 10, p.OFPMatch(eth_type=0x0806), [p.OFPActionOutput(of.OFPP_FLOOD)])
        self.emit('SWITCH_READY', dpid=dp.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def incoming(self, ev):
        msg, dp = ev.msg, ev.msg.datapath
        if dp.id != 1:
            return
        p, of = dp.ofproto_parser, dp.ofproto
        port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth, ip, segment = pkt.get_protocol(ethernet.ethernet), pkt.get_protocol(ipv4.ipv4), pkt.get_protocol(tcp.tcp)
        if not ip:
            if eth:
                self.flow(dp, 20, p.OFPMatch(in_port=port, eth_type=eth.ethertype), [], hard=10)
            return
        # No IP spoofing across the fixed host ports; fragments are unsupported.
        if PORTS.get(ip.src) != port or ip.dst not in PORTS or ip.offset or (ip.flags & 1):
            self.emit('INVALID_PACKET', src=ip.src, dst=ip.dst, in_port=port)
            return
        actions = [p.OFPActionOutput(PORTS[ip.dst])]
        if ip.proto == 1:
            match = p.OFPMatch(in_port=port, eth_type=0x0800, ipv4_src=ip.src, ipv4_dst=ip.dst, ip_proto=1)
            self.flow(dp, 50, match, actions, idle=5)
        elif segment:
            fields = dict(in_port=port, eth_type=0x0800, ipv4_src=ip.src, ipv4_dst=ip.dst,
                          ip_proto=6, tcp_src=segment.src_port, tcp_dst=segment.dst_port)
            match = p.OFPMatch(**fields)
            decision, count = ('ALLOW', 0) if self.mode == 'baseline' else self.policy.decide(
                ip.src, ip.dst, segment.src_port, segment.dst_port,
                bool(segment.bits & 2), bool(segment.bits & 16))
            if decision == 'BLOCKED':
                return
            if decision == 'BLOCK':
                self.cookie += 1
                cookie = self.cookie
                started = time.monotonic_ns()
                self.blocks[cookie] = (ip.src, started)
                # Higher priority than ALL allow rules, including established flows.
                self.flow(dp, 300, p.OFPMatch(in_port=port, eth_type=0x0800, ipv4_src=ip.src), [],
                          hard=self.policy.block_seconds, cookie=cookie, notify=True)
                barrier = p.OFPBarrierRequest(dp)
                dp.set_xid(barrier)
                self.pending[barrier.xid] = (ip.src, started)
                dp.send_msg(barrier)
                self.emit('BLOCK_REQUEST', src=ip.src, count=count, cookie=cookie,
                          block_seconds=self.policy.block_seconds, decision_ns=started)
                return
            self.emit(decision, src=ip.src, dst=ip.dst, sport=segment.src_port,
                      dport=segment.dst_port, count=count)
            if decision == 'DENY':
                # Exact-connection drop avoids counting SYN retransmissions again;
                # distinct source ports still reach the controller for classification.
                self.flow(dp, 200, match, [], hard=self.policy.window)
                return
            self.flow(dp, 100, match, actions, idle=5, hard=30)
            reverse = p.OFPMatch(in_port=PORTS[ip.dst], eth_type=0x0800,
                                ipv4_src=ip.dst, ipv4_dst=ip.src, ip_proto=6,
                                tcp_src=segment.dst_port, tcp_dst=segment.src_port)
            self.flow(dp, 100, reverse, [p.OFPActionOutput(port)], idle=5, hard=30)
        else:
            self.flow(dp, 20, p.OFPMatch(in_port=port, eth_type=0x0800,
                      ipv4_src=ip.src, ip_proto=ip.proto), [], hard=10)
            return
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=of.OFP_NO_BUFFER,
                    in_port=port, actions=actions, data=msg.data))

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier(self, ev):
        pending = self.pending.pop(ev.msg.xid, None)
        if pending:
            src, started = pending
            self.emit('BLOCK_CONFIRMED', src=src, decision_ns=started,
                      barrier_ms=(time.monotonic_ns()-started)/1e6)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def removed(self, ev):
        block = self.blocks.pop(ev.msg.cookie, None)
        if block:
            source, started = block
            self.policy.recover(source)
            self.emit('RECOVER', src=source, cookie=ev.msg.cookie,
                      elapsed_ms=(time.monotonic_ns()-started)/1e6,
                      switch_duration_s=ev.msg.duration_sec + ev.msg.duration_nsec/1e9,
                      dropped_packets=ev.msg.packet_count, reason=ev.msg.reason)

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error(self, ev):
        self.emit('OPENFLOW_ERROR', error_type=ev.msg.type, code=ev.msg.code)
