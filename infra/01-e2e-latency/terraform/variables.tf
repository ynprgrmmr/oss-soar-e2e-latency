# ---------------------------------------------------------------------------
# Account / placement
# ---------------------------------------------------------------------------
variable "oci_profile" {
  description = "Profile name in ~/.oci/config used for authentication."
  type        = string
  default     = "DEFAULT"
}

variable "region" {
  description = "OCI region (Always Free A1/E2.1.Micro must be in the home region)."
  type        = string
}

variable "compartment_ocid" {
  description = "Dedicated compartment for this lab (recommended so quotas/budgets can be scoped)."
  type        = string
}

variable "ad_index" {
  description = "Index into the list of availability domains (E2.1.Micro is often available in only one AD)."
  type        = number
  default     = 0
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key injected into Linux instances."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "CIDR allowed to reach SSH / dashboards from the internet (e.g. your home IP /32). Never commit the real value."
  type        = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a valid CIDR and must not be 0.0.0.0/0."
  }
}

# ---------------------------------------------------------------------------
# Lifecycle / tagging (used by the auto-stop design, see ../AUTO_STOP.md)
# ---------------------------------------------------------------------------
variable "project" {
  type    = string
  default = "soar-net-lab"
}

variable "experiment" {
  type    = string
  default = "01-e2e-latency"
}

variable "expires_at" {
  description = "RFC3339 timestamp after which this stack should be destroyed. Read by teardown tooling."
  type        = string
  default     = "1970-01-01T00:00:00Z"
}

variable "extra_tags" {
  type    = map(string)
  default = {}
}

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
variable "vcn_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CHR WAN + SOAR (Wazuh/Shuffle) VM."
  type        = string
  default     = "10.10.0.0/24"
}

variable "attacker_subnet_cidr" {
  description = "Attacker / prober VM. Its traffic to the protected subnet is forced through CHR."
  type        = string
  default     = "10.10.1.0/24"
}

variable "protected_subnet_cidr" {
  description = "Private subnet of the target VM. Default route points to CHR LAN."
  type        = string
  default     = "10.10.2.0/24"
}

variable "transit_subnet_cidr" {
  description = "single-nic mode only: dedicated subnet for the one-armed CHR (no CHR-steering routes, avoids loops)."
  type        = string
  default     = "10.10.3.0/24"
}

variable "chr_transit_ip" {
  description = "single-nic mode only: CHR address in the transit subnet."
  type        = string
  default     = "10.10.3.10"
}

variable "chr_wan_ip" {
  type    = string
  default = "10.10.0.10"
}

variable "chr_lan_ip" {
  type    = string
  default = "10.10.2.10"
}

variable "soar_ip" {
  type    = string
  default = "10.10.0.20"
}

variable "attacker_ip" {
  type    = string
  default = "10.10.1.20"
}

variable "target_ip" {
  type    = string
  default = "10.10.2.20"
}

# ---------------------------------------------------------------------------
# Compute
#   Always Free budget: A1.Flex 4 OCPU / 24 GB total, 2x E2.1.Micro,
#   200 GB total block storage (4 boot volumes x 50 GB = 200 GB).
# ---------------------------------------------------------------------------
variable "chr_mode" {
  description = <<-EOT
    dual-nic   : CHR on A1.Flex (arm64) with WAN + LAN VNICs (default).
    single-nic : CHR on E2.1.Micro (x86) with ONE VNIC in a transit subnet
                 (router-on-a-stick). The attacker VM moves to A1.Flex to
                 stay within the 2x E2.1.Micro Always Free limit.
  EOT
  type        = string
  default     = "dual-nic"

  validation {
    condition     = contains(["dual-nic", "single-nic"], var.chr_mode)
    error_message = "chr_mode must be dual-nic or single-nic."
  }
}

variable "chr_image_ocid" {
  description = "OCID of the imported MikroTik CHR custom image (arm64 for dual-nic/A1, x86_64 for single-nic/Micro). See ../README.md."
  type        = string
}

variable "chr_shape" {
  description = "Override CHR shape. null = A1.Flex for dual-nic, micro_shape for single-nic."
  type        = string
  default     = null
}

variable "chr_ocpus" {
  type    = number
  default = 1
}

variable "chr_memory_gbs" {
  type    = number
  default = 6
}

variable "soar_shape" {
  type    = string
  default = "VM.Standard.A1.Flex"
}

variable "soar_ocpus" {
  type    = number
  default = 3
}

variable "soar_memory_gbs" {
  type    = number
  default = 18
}

variable "attacker_a1_ocpus" {
  description = "single-nic mode only: attacker runs on A1.Flex with this many OCPUs (A1 budget: soar + this <= 4)."
  type        = number
  default     = 1
}

variable "attacker_a1_memory_gbs" {
  type    = number
  default = 6
}

variable "micro_shape" {
  description = "Shape for attacker and target (lightweight)."
  type        = string
  default     = "VM.Standard.E2.1.Micro"
}

variable "ubuntu_version" {
  description = "Canonical Ubuntu version string as listed by OCI images API."
  type        = string
  default     = "24.04"
}

variable "boot_volume_gbs" {
  type    = number
  default = 50
}
