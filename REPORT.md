# Dynamic Firewall with Security Event Logger
## Final implementation and experimental results

Computer Networks project | Submission date: 26 October 2026

Team members / student IDs: ______________________________
Course / instructor: ______________________________
Repository URL / commit (if required): ______________________________

## 1. Objective

Implement a TCP application integrated with a software-defined firewall and a centralized security event logger. The firewall permits configured TCP connections, detects repeated unauthorized connection attempts, temporarily blocks the offending source, and automatically restores access without affecting another client.

The policy counts three distinct unauthorized initial SYN connections within a rolling 10-second window and requests a 10-second source block. Retransmissions of the same connection tuple are counted once. This is an educational single-switch IPv4/TCP implementation.

## 2. Architecture and implementation

Two Mininet clients, h1 (10.0.0.1) and h2 (10.0.0.2), connect through Open vSwitch s1 to server h3 (10.0.0.3) and logger h4 (10.0.0.4). The OS-Ken controller runs outside the host namespaces and controls s1 over OpenFlow 1.3 at 127.0.0.1:6653. A separate management link connects the controller namespace (192.168.100.1) to h4 (192.168.100.2), allowing security logging independently of the data-switch policy.

The application uses newline-framed TCP messages, a threaded echo server, and concurrent clients. The central logger appends JSONL records, flushes and fsyncs each accepted record, then sends an acknowledgement. Events carry unique IDs and UTC timestamps. The controller also keeps a local event copy and queues central delivery outside its packet handler.

Allowed traffic is h1/h2 to h3 TCP 5000, and h3 to h4 TCP 7000 for application logging, with matching reply rules. TCP 9999 has a live test listener but is denied by the firewall. Other TCP connections are denied. ARP and ICMP are allowed for address resolution and diagnostics; unsupported protocols are dropped. Fixed ingress-port/IP checks constrain IPv4 source spoofing.

Ordinary allow rules use priority 100; exact-connection deny rules use priority 200. A source block uses priority 300 and hard_timeout=10, overriding pre-existing allows. A barrier response confirms switch processing, while a FlowRemoved event records expiry. Controller restart clears the in-memory strike state. Policy persistence in the demo means forbidden traffic remains forbidden after temporary recovery, not persistence across controller restarts.

## 3. Validated environment and execution

The project ran in the user's existing Ubuntu VM on a Windows laptop using VirtualBox. Terminal evidence identifies Ubuntu 26.04.1 LTS, Python 3.14.4, Mininet package 2.3.0-1.1build1, Open vSwitch 3.7.1-2, and OS-Ken 4.1.1-1ubuntu2. VM CPU/RAM allocation was not supplied, so it is not invented here. An independent machine-readable package inventory was not included in the archive.

OS-Ken uses the supplied controller_launcher.py and OSKEN_HUB_TYPE=eventlet, rather than the original Ubuntu-22.04-only virtual-environment launcher. The user reported all 20 unit tests completed after applying the logging update; their full final test transcript is not in the archive. The reviewed SDN evidence is suite 20261026-102714. Prior Mac/Windows proxy measurements are excluded from every SDN result in this report.

## 4. Acceptance results

The final suite completed its automated acceptance demo. Terminal evidence shows 0% ping loss (12/12 received) and successful concurrent-client operation. Saved demo records verify both clients can access the allowed service; three forbidden connections time out; h2 then cannot access the allowed port; h1 remains unaffected; h2 recovers automatically; and the forbidden port remains denied afterward. A denied connection is checked as a timeout, not accepted merely because a listener refused it.

| Measurement | Final observed value |
|---|---:|
| Threshold | 3 distinct unauthorized connections |
| Policy window / requested block | 10 s / 10 s |
| OpenFlow barrier confirmation | 5.457991 ms |
| Switch-reported block duration | 10.312 s |
| First successful recovery response after decision | 10.429786 s |
| Packets counted on temporary block rule | 16 |

The barrier measures switch processing, not the exact first dropped packet. The observed recovery time includes polling, scheduling and echo time. Switch timeout processing is not exact to the millisecond; the measured duration is reported rather than rounded into a claim of exactly 10 seconds. The packet count applies to this temporary rule, not all rejected traffic.

## 5. Benchmark method and results

The baseline uses the same controller, topology and services while bypassing TCP policy checks. Three rounds alternate order: baseline/firewall, firewall/baseline, baseline/firewall. Each condition has 30 measured fresh TCP connections per round, after a discarded warm-up. Each sample exchanges 200 sequential messages of 4096 payload bytes. All 180 samples succeeded (90 per condition).

Goodput is outgoing application payload divided by echo-loop time; it is not link capacity. Connection time includes handshake and initial flow setup. First echo includes server connection logging; steady echo median excludes the first exchange. The aggregate comparison is the median of three per-round medians, not a pooled mean.

| Round / mode | Successful samples | Connect ms | First echo ms | Steady echo ms | Payload goodput Mbps |
|---|---:|---:|---:|---:|---:|
| 1-baseline | 30/30 | 6.487 | 33.787 | 0.037 | 79.835 |
| 1-firewall | 30/30 | 6.281 | 29.318 | 0.030 | 115.245 |
| 2-baseline | 30/30 | 6.091 | 28.204 | 0.032 | 97.128 |
| 2-firewall | 30/30 | 6.777 | 28.724 | 0.048 | 105.771 |
| 3-baseline | 30/30 | 6.549 | 27.642 | 0.037 | 119.458 |
| 3-firewall | 30/30 | 5.942 | 31.596 | 0.024 | 84.993 |

| Median across round medians | Baseline | Firewall | Change |
|---|---:|---:|---:|
| Connect latency (ms) | 6.487 | 6.281 | -3.2% |
| First echo latency (ms) | 28.204 | 29.318 | +4.0% |
| Steady echo latency (ms) | 0.037 | 0.030 | -18.9% |
| Payload goodput (Mbps) | 97.128 | 105.771 | +8.9% |

The percentages use unrounded values. Firewall goodput was higher in the first two rounds and lower in the third. These mixed results and the variation between runs do not establish that filtering improves throughput. VM scheduling, storage synchronization and logging timeouts affect measurement; no statistical-significance claim is made. The earlier run's 5.3% decrease is not the final result and is not combined with this corrected run.

## 6. Central logging verification and remaining warnings

The earlier topology started the switch before the logger and stopped the logger before pending events had drained. The revised topology starts the logger before switch connection, requires central SWITCH_READY, waits for all newly recorded controller event IDs and server disconnects to appear centrally, and requires a one-second quiet interval before stopping services. A ten-second drain timeout fails the run. Application services stop before the logger.

All seven final runs produced passing logging-validation.json records. Independent archive review matched all 1,465 controller-local event IDs to central logs, with no missing controller events. There are 1,857 central records in total, with no duplicate event IDs within any run. No recorded OpenFlow errors or controller tracebacks were found in the final suite.

Fourteen LOGGER_UNAVAILABLE timeout warnings remain: seven controller and seven application-server warnings. Every affected event ID is present centrally. Thus persistence succeeded for these observed events, but the sender did not obtain a timely acknowledgement within its 0.3-second timeout. These are real acknowledgement failures and can affect timings; the submission must not claim warning-free or exactly-once delivery. The Eventlet deprecation and ungreened-RLock warning also remain. Their performance effect has not been isolated. The lifecycle fix is validated for this run; it does not eliminate all dependency warnings or provide durable retry/replay.

## 7. Limitations

The topology is fixed, with one switch and IPv4/TCP policy. It does not implement general routing, NAT, TLS inspection, authenticated ARP, full TCP state tracking, or fragment reassembly. The block filters outgoing IPv4 from one source, not bidirectional quarantine. ARP is still permitted. Logs have no authentication, TLS or rotation. Controller queuing is bounded and has no automatic replay. A passing run demonstrates the tested scenario, not production security or universal delivery guarantees.

## 8. Conclusion

The implementation demonstrated dynamic allow/deny rules, threshold-based blocking, client isolation, automatic recovery and centralized event persistence on an actual Ubuntu/Mininet/OpenFlow deployment. The final run completed 180 successful benchmark samples and preserved all observed controller events centrally. Performance values are reported as measurements under the tested VM conditions, with acknowledgement timeouts and dependency warnings disclosed.

## 9. Evidence and reproducibility

Use results/20261026-102714-summary.md for the original summary; each benchmark directory contains benchmark.jsonl, security.jsonl, service logs and logging-validation.json. The demo directory adds demo.json and recovery.json. Matching *-controller.jsonl and *-controller.log files provide local event and warning evidence. VERIFICATION.json records the independent audit. RUN-GUIDE.md explains starting the existing VM project and reproducing the demo/suite.

Add the team details and repository link above before submission. If the course separately requires a flow-table screenshot, VM resource inventory or repository publication, those items are not demonstrated by this archive. The supplied rubric checklist references such requirements, but the original rubric PDF was not independently available for this review.
