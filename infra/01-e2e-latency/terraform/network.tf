locals {
  name       = "${var.project}-${var.experiment}"
  single_nic = var.chr_mode == "single-nic"

  chr_primary_ip        = local.single_nic ? var.chr_transit_ip : var.chr_wan_ip
  chr_primary_subnet_id = local.single_nic ? oci_core_subnet.transit[0].id : oci_core_subnet.public.id

  tags = merge({
    "project"    = var.project
    "experiment" = var.experiment
    "managed-by" = "terraform"
    "expires-at" = var.expires_at
    "auto-stop"  = "true"
  }, var.extra_tags)
}

# ---------------------------------------------------------------------------
# VCN + Internet Gateway
# ---------------------------------------------------------------------------
resource "oci_core_vcn" "lab" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "${local.name}-vcn"
  dns_label      = "soarlab"
  freeform_tags  = local.tags
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${local.name}-igw"
  enabled        = true
  freeform_tags  = local.tags
}

# Bootstrap route table: every subnet starts with plain internet egress.
# The CHR-steering route tables below can only be built after CHR exists
# (they target CHR private-IP OCIDs), so they are attached afterwards via
# oci_core_route_table_attachment to avoid a dependency cycle.
resource "oci_core_default_route_table" "default" {
  manage_default_resource_id = oci_core_vcn.lab.default_route_table_id
  display_name               = "${local.name}-rt-default"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

# ---------------------------------------------------------------------------
# Security list (single, shared). Inside the VCN everything is allowed;
# enforcement under test happens on CHR, not here.
# ---------------------------------------------------------------------------
resource "oci_core_security_list" "lab" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${local.name}-sl"
  freeform_tags  = local.tags

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    source   = var.vcn_cidr
    protocol = "all"
  }

  # SSH from the operator only
  ingress_security_rules {
    source   = var.admin_cidr
    protocol = "6"
    tcp_options {
      min = 22
      max = 22
    }
  }

  # Wazuh dashboard (443) from the operator only
  ingress_security_rules {
    source   = var.admin_cidr
    protocol = "6"
    tcp_options {
      min = 443
      max = 443
    }
  }

  # Shuffle UI (3443) from the operator only
  ingress_security_rules {
    source   = var.admin_cidr
    protocol = "6"
    tcp_options {
      min = 3443
      max = 3443
    }
  }

  # Path MTU discovery
  ingress_security_rules {
    source   = "0.0.0.0/0"
    protocol = "1"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

# ---------------------------------------------------------------------------
# Subnets
# ---------------------------------------------------------------------------
resource "oci_core_subnet" "public" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.lab.id
  cidr_block        = var.public_subnet_cidr
  display_name      = "${local.name}-sn-public"
  dns_label         = "pub"
  security_list_ids = [oci_core_security_list.lab.id]
  freeform_tags     = local.tags
}

resource "oci_core_subnet" "attacker" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.lab.id
  cidr_block        = var.attacker_subnet_cidr
  display_name      = "${local.name}-sn-attacker"
  dns_label         = "atk"
  security_list_ids = [oci_core_security_list.lab.id]
  freeform_tags     = local.tags
}

resource "oci_core_subnet" "protected" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.lab.id
  cidr_block                 = var.protected_subnet_cidr
  display_name               = "${local.name}-sn-protected"
  dns_label                  = "prot"
  prohibit_public_ip_on_vnic = true
  security_list_ids          = [oci_core_security_list.lab.id]
  freeform_tags              = local.tags
}

# single-nic mode only: the one-armed CHR lives in its own subnet that keeps
# the VCN default route table (0/0 -> IGW, no CHR-steering rules). If CHR
# sat in a subnet whose route table points back at CHR, packets it forwards
# out of its single VNIC would be routed straight back to it (loop).
resource "oci_core_subnet" "transit" {
  count = local.single_nic ? 1 : 0

  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.lab.id
  cidr_block        = var.transit_subnet_cidr
  display_name      = "${local.name}-sn-transit"
  dns_label         = "transit"
  security_list_ids = [oci_core_security_list.lab.id]
  freeform_tags     = local.tags
}

# ---------------------------------------------------------------------------
# CHR private-IP lookups (route targets)
#   dual-nic  : traffic enters on WAN (primary VNIC), target side uses LAN
#   single-nic: both "sides" are the same (only) VNIC
# ---------------------------------------------------------------------------
data "oci_core_private_ips" "chr_primary" {
  ip_address = local.chr_primary_ip
  subnet_id  = local.chr_primary_subnet_id

  depends_on = [oci_core_instance.chr]
}

data "oci_core_private_ips" "chr_lan" {
  count   = local.single_nic ? 0 : 1
  vnic_id = oci_core_vnic_attachment.chr_lan[0].vnic_id
}

locals {
  chr_wan_private_ip_id = data.oci_core_private_ips.chr_primary.private_ips[0].id
  chr_lan_private_ip_id = local.single_nic ? local.chr_wan_private_ip_id : data.oci_core_private_ips.chr_lan[0].private_ips[0].id
}

# ---------------------------------------------------------------------------
# CHR-steering route tables (intra-VCN routing)
#
#   attacker/public --(dst protected)--> CHR WAN --> CHR LAN --> target
#   target --(dst anything, incl. other subnets)--> CHR LAN
#
# Both directions traverse CHR, so the path is symmetric and the
# Address-List drop on CHR is the single enforcement point.
# ---------------------------------------------------------------------------
resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${local.name}-rt-public"
  freeform_tags  = local.tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }

  route_rules {
    destination       = var.protected_subnet_cidr
    destination_type  = "CIDR_BLOCK"
    network_entity_id = local.chr_wan_private_ip_id
  }
}

resource "oci_core_route_table" "attacker" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${local.name}-rt-attacker"
  freeform_tags  = local.tags

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }

  route_rules {
    destination       = var.protected_subnet_cidr
    destination_type  = "CIDR_BLOCK"
    network_entity_id = local.chr_wan_private_ip_id
  }
}

resource "oci_core_route_table" "protected" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${local.name}-rt-protected"
  freeform_tags  = local.tags

  # Internet egress (apt, Wazuh packages) via CHR masquerade
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = local.chr_lan_private_ip_id
  }

  # More-specific intra-VCN routes override the implicit VCN-local route,
  # keeping return traffic symmetric through CHR.
  route_rules {
    destination       = var.public_subnet_cidr
    destination_type  = "CIDR_BLOCK"
    network_entity_id = local.chr_lan_private_ip_id
  }

  route_rules {
    destination       = var.attacker_subnet_cidr
    destination_type  = "CIDR_BLOCK"
    network_entity_id = local.chr_lan_private_ip_id
  }
}

resource "oci_core_route_table_attachment" "public" {
  subnet_id      = oci_core_subnet.public.id
  route_table_id = oci_core_route_table.public.id
}

resource "oci_core_route_table_attachment" "attacker" {
  subnet_id      = oci_core_subnet.attacker.id
  route_table_id = oci_core_route_table.attacker.id
}

resource "oci_core_route_table_attachment" "protected" {
  subnet_id      = oci_core_subnet.protected.id
  route_table_id = oci_core_route_table.protected.id
}
