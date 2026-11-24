# Public IPs are printed for the operator only. Do NOT paste them into
# committed files (experiments/, articles/). Use private IPs in write-ups.

output "chr_public_ip" {
  value = oci_core_instance.chr.public_ip
}

output "soar_public_ip" {
  value = oci_core_instance.linux["soar"].public_ip
}

output "attacker_public_ip" {
  value = oci_core_instance.linux["attacker"].public_ip
}

output "private_ips" {
  value = {
    chr_mode = var.chr_mode
    chr_wan  = local.chr_primary_ip
    chr_lan  = local.single_nic ? local.chr_primary_ip : var.chr_lan_ip
    soar     = var.soar_ip
    attacker = var.attacker_ip
    target   = var.target_ip
  }
}

output "ssh_hints" {
  value = {
    soar     = "ssh ubuntu@<soar_public_ip>"
    attacker = "ssh ubuntu@<attacker_public_ip>"
    target   = "ssh -J ubuntu@<soar_public_ip> ubuntu@${var.target_ip}"
    chr      = "ssh -J ubuntu@<soar_public_ip> admin@${local.chr_primary_ip}"
  }
}
