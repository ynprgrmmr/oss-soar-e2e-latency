# RouterOS v7 bootstrap — chr_mode = "single-nic" (x86 CHR on E2.1.Micro)
#
# One-armed router: ether1 only, transit subnet 10.10.3.0/24 (10.10.3.10).
# OCI route tables steer attacker/public <-> protected traffic to this VNIC;
# CHR forwards it back out of the same interface via the VCN gateway
# 10.10.3.1 (transit subnet keeps the plain IGW route table, so no loop).
#
# Placeholders (render to a temp file, never commit):
#   __ADMIN_PASSWORD__, __API_PASSWORD__

/system identity set name=soar-lab-chr

# Factory admin has an EMPTY password: set it first.
/user set admin password="__ADMIN_PASSWORD__"
/system clock set time-zone-name=UTC
/system ntp client set enabled=yes servers=169.254.169.254

# ether1 keeps the default DHCP client (10.10.3.10, default gw 10.10.3.1).

# Hairpin forwarding: never tell hosts to bypass us via ICMP redirects,
# that would silently skip the enforcement point.
/ip settings set send-redirects=no

# Protected subnet -> internet (same interface in and out)
/ip firewall nat add chain=srcnat out-interface=ether1 src-address=10.10.2.0/24 \
    dst-address=!10.10.0.0/16 action=masquerade comment="protected subnet egress"

# ---------------------------------------------------------------------------
# Enforcement point (identical to dual-nic so results stay comparable)
# ---------------------------------------------------------------------------
/ip firewall raw add chain=prerouting src-address-list=soar-blocklist action=drop \
    comment="SOAR-A: raw drop (pre-conntrack)"

/ip firewall filter add chain=forward src-address-list=soar-blocklist action=drop \
    disabled=yes comment="SOAR-B: filter drop (post-conntrack)"
# NOTE: the factory filter list on CHR is empty, so no place-before here
# (place-before=0 fails on an empty list). If you add an
# "accept established,related" rule later, move SOAR-B above it.

# ---------------------------------------------------------------------------
# REST API (www-ssl) reachable from the public subnet (Shuffle) only
# ---------------------------------------------------------------------------
/certificate add name=soar-lab-ca common-name=soar-lab-ca key-usage=key-cert-sign,crl-sign days-valid=365
/certificate sign soar-lab-ca
:delay 5s
/certificate add name=chr-rest common-name=10.10.3.10 subject-alt-name=IP:10.10.3.10 days-valid=365
/certificate sign chr-rest ca=soar-lab-ca
:delay 5s

/ip service set www-ssl certificate=chr-rest disabled=no address=10.10.0.0/24
/ip service set www disabled=yes
/ip service set api disabled=yes
/ip service set api-ssl disabled=yes
/ip service set telnet disabled=yes
/ip service set ftp disabled=yes
/ip service set winbox disabled=yes
# reverse-proxy (443/tcp, no source restriction) is enabled by default on
# RouterOS 7.25.x. Older releases do not have it, so ignore errors.
:do { /ip service set [find name=reverse-proxy] disabled=yes } on-error={ :put "no reverse-proxy service" }
/ip service set ssh address=10.10.0.0/24

/user group add name=soar-api policy=read,write,api,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon
/user add name=soar-api group=soar-api address=10.10.0.0/24 password="__API_PASSWORD__"

/certificate export-certificate soar-lab-ca file-name=soar-lab-ca
