data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid
}

locals {
  ad = data.oci_identity_availability_domains.ads.availability_domains[var.ad_index].name

  a1_shape  = "VM.Standard.A1.Flex"
  chr_shape = coalesce(var.chr_shape, local.single_nic ? var.micro_shape : local.a1_shape)

  # Linux nodes. CHR is defined separately (custom image).
  # In single-nic mode CHR takes an E2.1.Micro slot, so the attacker moves to
  # A1.Flex (also gives T0/T3 timestamps a non-burstable CPU).
  linux_nodes = {
    soar = {
      shape     = var.soar_shape
      ocpus     = var.soar_ocpus
      memory    = var.soar_memory_gbs
      subnet_id = oci_core_subnet.public.id
      ip        = var.soar_ip
      public_ip = true
      image_key = "arm"
    }
    attacker = {
      shape     = local.single_nic ? local.a1_shape : var.micro_shape
      ocpus     = local.single_nic ? var.attacker_a1_ocpus : null
      memory    = local.single_nic ? var.attacker_a1_memory_gbs : null
      subnet_id = oci_core_subnet.attacker.id
      ip        = var.attacker_ip
      public_ip = true
      image_key = local.single_nic ? "arm" : "x86"
    }
    target = {
      shape     = var.micro_shape
      ocpus     = null
      memory    = null
      subnet_id = oci_core_subnet.protected.id
      ip        = var.target_ip
      public_ip = false
      image_key = "x86"
    }
  }

  image_ids = {
    arm = data.oci_core_images.ubuntu_arm.images[0].id
    x86 = data.oci_core_images.ubuntu_x86.images[0].id
  }
}

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = var.ubuntu_version
  shape                    = local.a1_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

data "oci_core_images" "ubuntu_x86" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = var.ubuntu_version
  shape                    = var.micro_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# ---------------------------------------------------------------------------
# MikroTik CHR (router under test)
#   dual-nic  : ether1 = WAN (public subnet, public IP for NAT egress)
#               ether2 = LAN (protected subnet)
#   single-nic: ether1 only, in the transit subnet (router-on-a-stick)
#   skip_source_dest_check = true on every CHR VNIC, otherwise OCI drops
#   forwarded packets whose src/dst is not the VNIC's own IP.
# ---------------------------------------------------------------------------
resource "oci_core_instance" "chr" {
  availability_domain = local.ad
  compartment_id      = var.compartment_ocid
  display_name        = "${local.name}-chr"
  shape               = local.chr_shape
  freeform_tags       = merge(local.tags, { "role" = "router", "chr-mode" = var.chr_mode })

  dynamic "shape_config" {
    for_each = can(regex("Flex$", local.chr_shape)) ? [1] : []
    content {
      ocpus         = var.chr_ocpus
      memory_in_gbs = var.chr_memory_gbs
    }
  }

  create_vnic_details {
    subnet_id              = local.chr_primary_subnet_id
    private_ip             = local.chr_primary_ip
    assign_public_ip       = true
    skip_source_dest_check = true
    display_name           = local.single_nic ? "chr-onearm" : "chr-wan"
    hostname_label         = "chr"
  }

  source_details {
    source_type             = "image"
    source_id               = var.chr_image_ocid
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  preserve_boot_volume = false
}

resource "oci_core_vnic_attachment" "chr_lan" {
  count = local.single_nic ? 0 : 1

  instance_id  = oci_core_instance.chr.id
  display_name = "chr-lan"

  create_vnic_details {
    subnet_id              = oci_core_subnet.protected.id
    private_ip             = var.chr_lan_ip
    assign_public_ip       = false
    skip_source_dest_check = true
    display_name           = "chr-lan"
    freeform_tags          = local.tags
  }
}

# ---------------------------------------------------------------------------
# Linux nodes: soar (Wazuh + Shuffle), attacker (prober), target (agent)
# ---------------------------------------------------------------------------
resource "oci_core_instance" "linux" {
  for_each = local.linux_nodes

  availability_domain = local.ad
  compartment_id      = var.compartment_ocid
  display_name        = "${local.name}-${each.key}"
  shape               = each.value.shape
  freeform_tags       = merge(local.tags, { "role" = each.key })

  dynamic "shape_config" {
    for_each = each.value.ocpus == null ? [] : [1]
    content {
      ocpus         = each.value.ocpus
      memory_in_gbs = each.value.memory
    }
  }

  create_vnic_details {
    subnet_id        = each.value.subnet_id
    private_ip       = each.value.ip
    assign_public_ip = each.value.public_ip
    hostname_label   = each.key
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_ids[each.value.image_key]
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
  }

  preserve_boot_volume = false

  # Target's internet access depends on CHR being configured (NAT),
  # so make sure the router exists first.
  depends_on = [oci_core_instance.chr, oci_core_vnic_attachment.chr_lan]
}

# ---------------------------------------------------------------------------
# Always Free fit (warning only; plan still proceeds)
# ---------------------------------------------------------------------------
check "always_free_a1_budget" {
  assert {
    condition = sum([
      for n in concat(
        [{ shape = local.chr_shape, ocpus = var.chr_ocpus }],
        [for k, v in local.linux_nodes : { shape = v.shape, ocpus = coalesce(v.ocpus, 0) }],
      ) : n.ocpus if n.shape == local.a1_shape
    ]) <= 4
    error_message = "A1.Flex OCPUs exceed the Always Free total of 4."
  }

  assert {
    condition = length([
      for s in concat([local.chr_shape], [for v in values(local.linux_nodes) : v.shape]) : s
      if s == "VM.Standard.E2.1.Micro"
    ]) <= 2
    error_message = "More than 2 E2.1.Micro instances (Always Free limit)."
  }
}
