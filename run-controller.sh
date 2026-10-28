#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export OSKEN_HUB_TYPE=eventlet
export EVENTLET_NO_GREENDNS=yes
export FW_MODE="${1:-firewall}"
mkdir -p results
exec /usr/bin/python3 -u controller_launcher.py
