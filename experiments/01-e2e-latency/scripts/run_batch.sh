#!/usr/bin/env bash
# Run N trials back to back on the attacker VM.
#   ./run_batch.sh <condition> <n> [target] [out_dir]
# Before each trial, waits until the previous block has expired (UDP echo
# answers again), so every trial starts from an unblocked state.
set -uo pipefail
COND="${1:?condition}"; N="${2:?n}"; TARGET="${3:-10.10.2.20}"
OUT="${4:-$HOME/e2e/raw}"; HERE="$(cd "$(dirname "$0")" && pwd)"
COOLDOWN_S="${COOLDOWN_S:-5}"; UNBLOCK_WAIT_S="${UNBLOCK_WAIT_S:-180}"
# Random extra delay before each trial (seconds, float). Without it the trial
# cadence can phase-lock to periodic loops on the path (the Wazuh agent's
# logcollector reads journald every 2 s), which biases D_detect.
# Observed in the first C4 batch: phase concentration R = 0.86 vs 0.24 in C1.
JITTER_MAX_S="${JITTER_MAX_S:-4}"

echo_ok() {
  python3 - "$TARGET" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(0.5)
try:
    s.sendto(b"SOARLAB1" + bytes(16), (sys.argv[1], 9999)); s.recvfrom(64)
except OSError:
    sys.exit(1)
PY
}

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
log "batch start condition=$COND n=$N target=$TARGET"
for i in $(seq 1 "$N"); do
  waited=0
  until echo_ok; do
    sleep 2; waited=$((waited + 2))
    if (( waited >= UNBLOCK_WAIT_S )); then log "trial $i: target still unreachable after ${UNBLOCK_WAIT_S}s, abort"; exit 2; fi
  done
  sleep "$COOLDOWN_S"
  sleep "$(python3 -c "import random; print(round(random.uniform(0, $JITTER_MAX_S), 3))")"
  res="$(python3 "$HERE/run_trial.py" --target "$TARGET" --condition "$COND" --out-dir "$OUT" 2>&1 | tail -1)"
  log "trial $i/$N $res"
done
log "batch done"
