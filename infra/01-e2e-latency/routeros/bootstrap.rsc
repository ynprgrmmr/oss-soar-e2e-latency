# RouterOS v7 bootstrap for soar-net-lab / 01-e2e-latency CHR
#
# Apply once after first boot (paste via console / SSH, or `/import bootstrap.rsc`).
# Interfaces assume: ether1 = WAN (public subnet), ether2 = LAN (protected subnet).
# Verify with `/interface print` - secondary VNIC may need a reboot to appear.
#
# Placeholders to replace before import (render to a temp file, never commit):
#   __ADMIN_PASSWORD__ -> admin password
#   __API_PASSWORD__   -> strong password for the SOAR REST user

/system identity set name=soar-lab-chr

# Factory admin has an EMPTY password: set it first.
/user set admin password="__ADMIN_PASSWORD__"
/system clock set time-zone-name=UTC
/system ntp client set enabled=yes servers=169.254.169.254

# ---------------------------------------------------------------------------
# Addressing / routing
#   ether1 keeps the default DHCP client (OCI DHCP returns 10.10.0.10 + gw).
#   ether2 is static (secondary VNIC).
# ---------------------------------------------------------------------------
/ip address add address=10.10.2.10/24 interface=ether2 comment="LAN / protected subnet"

# Target -> internet egress
/ip firewall nat add chain=srcnat out-interface=ether1 src-address=10.10.2.0/24 \
    dst-address=!10.10.0.0/16 action=masquerade comment="protected subnet egress"

# ---------------------------------------------------------------------------
# Enforcement point under test
#   soar-blocklist is populated by Shuffle through the REST API.
#
#   Variant A (default, enabled):  raw/prerouting drop
#     - evaluated before connection tracking, so ESTABLISHED flows are cut
#       immediately (important for T3).
#   Variant B (disabled):          filter/forward drop
#     - placed above the usual "accept established,related" rule; useful as
#       a comparison condition in the experiment.
# ---------------------------------------------------------------------------
/ip firewall raw add chain=prerouting src-address-list=soar-blocklist action=drop \
    comment="SOAR-A: raw drop (pre-conntrack)"

/ip firewall filter add chain=forward src-address-list=soar-blocklist action=drop \
    disabled=yes comment="SOAR-B: filter drop (post-conntrack)"
# NOTE: the factory filter list on CHR is empty, so no place-before here
# (place-before=0 fails on an empty list). If you add an
# "accept established,related" rule later, move SOAR-B above it.

# ---------------------------------------------------------------------------
# REST API (www-ssl) restricted to the public subnet where Shuffle runs
# ---------------------------------------------------------------------------
/certificate add name=soar-lab-ca common-name=soar-lab-ca key-usage=key-cert-sign,crl-sign days-valid=365
/certificate sign soar-lab-ca
:delay 5s
/certificate add name=chr-rest common-name=10.10.0.10 subject-alt-name=IP:10.10.0.10 days-valid=365
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

# Least-privilege user for SOAR. Verify policy names on your RouterOS version
# (`/user group print`); `rest-api` exists on recent v7 releases.
/user group add name=soar-api policy=read,write,api,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon
/user add name=soar-api group=soar-api address=10.10.0.0/24 password="__API_PASSWORD__"

# Export CA so clients can verify TLS: copy soar-lab-ca.crt to the SOAR VM.
/certificate export-certificate soar-lab-ca file-name=soar-lab-ca
