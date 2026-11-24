#!/usr/bin/env bash
# Record clock sync state on this host. Run on attacker / target / soar
# before and after each batch:
#   ./clock_snapshot.sh ../raw/<batch>
set -euo pipefail
out_dir="${1:?usage: clock_snapshot.sh <out-dir>}"
mkdir -p "$out_dir"
f="$out_dir/clock-$(hostname)-$(date -u +%Y%m%dT%H%M%SZ).txt"
{
  echo "# host=$(hostname) utc=$(date -u +%FT%T.%NZ)"
  chronyc -n tracking
  echo
  chronyc -n sources -v
} > "$f"
grep -E 'System time|Last offset|RMS offset' "$f"
