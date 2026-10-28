# Run the final project in the existing Ubuntu VM

## Already installed VM

Keep the project on Ubuntu's local disk. The validated setup uses Ubuntu 26.04.1 / Python 3.14.4 with Ubuntu-packaged Mininet, Open vSwitch and OS-Ken 4.1.1. VS Code is optional. No new VM is needed.

From the existing working folder:

```bash
cd ~/Downloads/CN-PROJECT-UBUNTU-MININET
```

If using the final submission ZIP, extract it into Downloads and use `cd ~/Downloads/dynamic-firewall-final` instead. All remaining commands are the same.

## Run the whole suite

Stop any manually started controller with Ctrl+C first. Check the port:

```bash
sudo ss -ltnp 'sport = :6653'
```

When no LISTEN row remains:

```bash
chmod +x run-controller.sh run-suite.sh
bash run-suite.sh
```

The suite starts and stops its own controllers. It runs the acceptance demo and six benchmark runs. Expect LOG DELIVERY PASSED for each run and Suite completed at the end. Results go into fresh timestamped directories; old evidence is preserved.

## Run just the firewall demonstration

Terminal A, in the project folder:

```bash
bash run-controller.sh firewall
```

Leave it open. Terminal B, in the same folder:

```bash
sudo python3 topology.py --action demo --tag viva-demo-1
```

Choose a new tag on every run. Expect DEMO PASSED and then LOG DELIVERY PASSED. After Terminal B returns to its prompt, stop Terminal A with Ctrl+C. An ordinary KeyboardInterrupt traceback on manual shutdown can occur. If port 6653 remains occupied, identify the process before stopping it; do not start a second controller.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The expected count is 20. The outage test intentionally simulates a missing logger. These unit/socket tests are separate from SDN acceptance. The legacy tests/controller_smoke.py expects the old virtual-environment launcher and is not part of this command; it is not claimed as rerun on this newer setup.

## Optional interactive presentation

With the controller running, start:

```bash
sudo python3 topology.py --action cli --tag viva-interactive-1
```

At the mininet> prompt:

```text
h1 python3 client.py --count 5
h2 python3 client.py --port 9999 --timeout 0.5
h2 python3 client.py --port 9999 --timeout 0.5
h2 python3 client.py --port 9999 --timeout 0.5
h2 python3 client.py --timeout 0.5
h1 python3 client.py --count 5
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

Issue the three denied attempts within ten seconds. Show the priority-300 block promptly before expiry. After ten seconds from the third attempt, h2's allowed port should work again. Use `exit` to stop the topology before stopping the controller. Do not run the interactive topology alongside the suite.

## Existing final evidence

Reviewed final run: 20261026-102714. The report discloses acknowledgement timeouts and the remaining Eventlet/RLock warning. Do not describe it as warning-free. No further benchmark run is necessary merely to reproduce evidence already present in this submission.

The original setup-ubuntu.sh targets Ubuntu 22.04 and is deliberately not used here. The controller uses system packages and controller_launcher.py, with OSKEN_HUB_TYPE=eventlet and EVENTLET_NO_GREENDNS=yes set by run-controller.sh. For installation on a different machine, revalidate dependencies and versions rather than assuming the same performance or compatibility.

## Dependency prerequisites for another reviewer

The working VM was prepared with Ubuntu packages `mininet`, `openvswitch-switch`, `python3-venv`, `python3-pip`, `python3-os-ken` and `unzip`. The OS-Ken package supplies its dependent Python libraries, including Eventlet. Open vSwitch must be running (`sudo systemctl enable --now openvswitch-switch`). A basic network check is `sudo mn --switch ovsbr --test pingall`.

These are recorded prerequisites, not an instruction to reinstall the working VM. Match the versions stated in REPORT.md and verify any different environment. Do not replace the working system-package launcher with the old .venv/osken-manager command.

