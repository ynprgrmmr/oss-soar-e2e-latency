#!/usr/bin/env bash
# Restrict Docker-published Shuffle ports. Docker DNATs published ports in
# PREROUTING, so they bypass the host INPUT chain; DOCKER-USER is the hook.
# Usage: docker-user-rules.sh <admin_cidr> [external_if]
#   external_if defaults to the default-route interface. Do not hardcode it:
#   it differs by shape (A1.Flex: enp0s6, E2.1.Micro: ens3).
# Installed as a oneshot systemd unit that runs after docker.service.
set -euo pipefail
ADMIN_CIDR="${1:?admin cidr}"
EXT_IF="${2:-$(ip route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')}"
[[ -n "$EXT_IF" ]] || { echo "cannot determine external interface" >&2; exit 1; }

# Remove previous soar-lab rules (e.g. ones written for another interface).
# Delete by rule number, highest first (iptables -S output has quoted
# comments that do not survive word splitting).
for n in $(iptables -L DOCKER-USER --line-numbers -n | awk '/soar-lab:/ {print $1}' | sort -rn); do
  iptables -D DOCKER-USER "$n"
done

# Inserted in reverse order (each -I goes to the top).
iptables -I DOCKER-USER -i "$EXT_IF" -p tcp -m conntrack --ctorigdstport 3443 -m comment --comment "soar-lab: shuffle 3443 others" -j DROP
iptables -I DOCKER-USER -i "$EXT_IF" -p tcp -m conntrack --ctorigdstport 3443 -s "$ADMIN_CIDR" -m comment --comment "soar-lab: shuffle 3443 operator" -j RETURN
echo "external interface: $EXT_IF"
iptables -S DOCKER-USER
