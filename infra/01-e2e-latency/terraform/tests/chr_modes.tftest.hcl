# Offline tests for both CHR modes: `terraform test` with a mocked provider.
# `command = apply` runs against the mock only — nothing is created in OCI.

mock_provider "oci" {
  mock_data "oci_identity_availability_domains" {
    defaults = {
      availability_domains = [{ name = "TEST:PHX-AD-1" }]
    }
  }

  mock_data "oci_core_images" {
    defaults = {
      images = [{ id = "ocid1.image.oc1..mock" }]
    }
  }
}

override_data {
  target = data.oci_core_private_ips.chr_primary
  values = {
    private_ips = [{ id = "ocid1.privateip.oc1..chr-primary" }]
  }
}

override_data {
  target = data.oci_core_private_ips.chr_lan[0]
  values = {
    private_ips = [{ id = "ocid1.privateip.oc1..chr-lan" }]
  }
}

variables {
  region              = "us-phoenix-1"
  compartment_ocid    = "ocid1.compartment.oc1..lab"
  chr_image_ocid      = "ocid1.image.oc1..chr"
  admin_cidr          = "203.0.113.10/32"
  ssh_public_key_path = "tests/fixtures/dummy.pub"

  # Pin values a local (git-ignored) terraform.tfvars might override.
  oci_profile = "DEFAULT"
  chr_mode    = "dual-nic"
  chr_shape   = null
  soar_ocpus  = 3
}

run "dual_nic_default" {
  command = apply

  assert {
    condition     = oci_core_instance.chr.shape == "VM.Standard.A1.Flex"
    error_message = "dual-nic CHR should run on A1.Flex."
  }

  assert {
    condition     = length(oci_core_vnic_attachment.chr_lan) == 1 && length(oci_core_subnet.transit) == 0
    error_message = "dual-nic needs the LAN VNIC and no transit subnet."
  }

  assert {
    condition     = oci_core_instance.linux["attacker"].shape == "VM.Standard.E2.1.Micro"
    error_message = "attacker should be on Micro in dual-nic mode."
  }

  assert {
    condition     = alltrue([for r in oci_core_route_table.protected.route_rules : r.network_entity_id == "ocid1.privateip.oc1..chr-lan"])
    error_message = "protected subnet must route everything to CHR LAN."
  }

  assert {
    condition     = contains([for r in oci_core_route_table.attacker.route_rules : r.network_entity_id if r.destination == var.protected_subnet_cidr], "ocid1.privateip.oc1..chr-primary")
    error_message = "attacker -> protected must go to CHR WAN."
  }
}

run "single_nic_micro" {
  command = apply
  # Fresh state: this models a clean single-nic build, not an in-place
  # switch from dual-nic (switching modes = destroy + apply, see README).
  state_key = "single_nic"

  variables {
    chr_mode = "single-nic"
  }

  assert {
    condition     = oci_core_instance.chr.shape == "VM.Standard.E2.1.Micro"
    error_message = "single-nic CHR should run on E2.1.Micro."
  }

  assert {
    condition     = length(oci_core_vnic_attachment.chr_lan) == 0 && length(oci_core_subnet.transit) == 1
    error_message = "single-nic: no LAN VNIC, transit subnet present."
  }

  assert {
    condition     = oci_core_instance.chr.create_vnic_details[0].private_ip == var.chr_transit_ip
    error_message = "single-nic CHR must sit in the transit subnet."
  }

  assert {
    condition     = oci_core_instance.linux["attacker"].shape == "VM.Standard.A1.Flex"
    error_message = "attacker should move to A1.Flex to free a Micro slot."
  }

  assert {
    condition = alltrue(concat(
      [for r in oci_core_route_table.protected.route_rules : r.network_entity_id == "ocid1.privateip.oc1..chr-primary"],
      [for r in oci_core_route_table.attacker.route_rules : r.network_entity_id == "ocid1.privateip.oc1..chr-primary" if r.destination == var.protected_subnet_cidr],
    ))
    error_message = "All CHR-steering routes must target the single CHR VNIC."
  }

  assert {
    condition     = output.private_ips.chr_lan == var.chr_transit_ip
    error_message = "outputs should report the one-armed address."
  }
}

run "a1_overcommit_is_flagged" {
  command = plan

  variables {
    soar_ocpus = 4
  }

  expect_failures = [check.always_free_a1_budget]
}

run "rejects_unknown_mode" {
  command = plan

  variables {
    chr_mode = "triple-nic"
  }

  expect_failures = [var.chr_mode]
}
