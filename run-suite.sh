#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
sudo -v
suite="$(date +%Y%m%d-%H%M%S)"
controller_pid=''
cleanup() {
  if [[ -n "$controller_pid" ]]; then
    kill "$controller_pid" 2>/dev/null || true
    wait "$controller_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
run() {
  local mode="$1" action="$2" tag="$3"
  FW_LOCAL_LOG="results/$tag-controller.jsonl" ./run-controller.sh "$mode" > "results/$tag-controller.log" 2>&1 &
  controller_pid=$!
  sleep 3
  kill -0 "$controller_pid" || { cat "results/$tag-controller.log"; exit 1; }
  sudo python3 topology.py --action "$action" --mode "$mode" --tag "$tag" --controller-log "results/$tag-controller.jsonl"
  cleanup
  controller_pid=''
}
run firewall demo "$suite-demo"
# Alternate order between rounds to reduce warm-up/order bias.
for round in 1 2 3; do
  if [[ "$round" == 2 ]]; then modes='firewall baseline'; else modes='baseline firewall'; fi
  for mode in $modes; do run "$mode" bench "$suite-$round-$mode"; done
done
python3 summarize.py --prefix "$suite"
echo "Suite completed: $suite (raw measurements under results/)"
