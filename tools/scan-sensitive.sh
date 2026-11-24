#!/usr/bin/env bash
# Pre-publication scan: working tree AND full git history (a public repo
# exposes both). Exit 1 if anything needs attention.
#
#   tools/scan-sensitive.sh [--extra-pattern REGEX]...
#
# Allowed on purpose: private ranges, 127/8, 169.254.169.254 (OCI metadata/NTP),
# documentation ranges 192.0.2.0/24 and 203.0.113.0/24, example.com addresses,
# GitHub noreply addresses, placeholder OCIDs (ocid1...xxxx).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
EXTRA=()
while [[ $# -gt 0 ]]; do case "$1" in --extra-pattern) EXTRA+=("$2"); shift 2 ;; *) echo "unknown arg $1" >&2; exit 2 ;; esac; done

HIST="$(mktemp)"; TREE="$(mktemp)"; trap 'rm -f "$HIST" "$TREE"' EXIT
git log -p --all --no-color > "$HIST"
git ls-files -z | xargs -0 cat 2>/dev/null > "$TREE"
fail=0

report() {  # label, matches
  if [[ -n "$2" ]]; then echo "FAIL  $1: $(echo "$2" | head -10 | tr '\n' ' ')"; fail=1; else echo "ok    $1"; fi
}

global_ips() {
  grep -Eoh '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' "$1" | sort -u | python3 -I -c '
import sys, ipaddress
doc = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
for l in sys.stdin:
    try: ip = ipaddress.ip_address(l.strip())
    except ValueError: continue
    if ip.is_global and not any(ip in n for n in doc): print(ip)'
}

for src in TREE HIST; do
  f="${!src}"; where=$([[ $src == TREE ]] && echo tree || echo history)
  report "$where: global IPv4" "$(global_ips "$f")"
  report "$where: real OCIDs" "$(grep -Eoh 'ocid1\.[a-z]+\.oc1\.[a-z0-9-]*\.[a-z0-9]{40,}' "$f" | sort -u)"
  report "$where: private keys / tokens" "$(grep -Eoh 'BEGIN [A-Z ]*PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]+' "$f" | sort -u)"
  report "$where: email addresses" "$(grep -Eoh '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$f" | grep -Ev '@(example\.(com|org)|users\.noreply\.github\.com|anthropic\.com)$' | sort -u)"
  report "$where: API key fingerprints" "$(grep -Eoh '\b([0-9a-f]{2}:){15}[0-9a-f]{2}\b' "$f" | sort -u)"
  report "$where: MAC addresses" "$(grep -Eoih '\b([0-9a-f]{2}:){5}[0-9a-f]{2}\b' "$f" | sort -u)"
  for p in "${EXTRA[@]}"; do report "$where: extra /$p/" "$(grep -Eoh "$p" "$f" | sort -u)"; done
done
report "files that must never be committed" "$(git log --all --name-only --format= | sort -u | grep -Ei '\.tfstate|\.tfvars$|\.tfplan$|\.pem$|(^|/)\.env$|client\.keys|authd\.pass|chr\.env|\.backup$|id_(rsa|ed25519)$')"
report "commit author/committer emails" "$(git log --all --format='%ae%n%ce' | sort -u | grep -Ev '@(users\.noreply\.github\.com|anthropic\.com)$|^noreply@github\.com$')"
exit $fail
