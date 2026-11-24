variable "oci_profile" {
  description = "Least-privilege deploy profile (needs object-family + instance-images in the lab compartment)."
  type        = string
  default     = "SOAR_DEPLOY"
}

variable "region" {
  description = "Tenancy home region (us-phoenix-1). The image must live where the instances run."
  type        = string
}

variable "compartment_ocid" {
  type = string
}

variable "project" {
  type    = string
  default = "soar-net-lab"
}

variable "bucket_name" {
  type    = string
  default = "soar-net-lab-images"
}

variable "chr_version" {
  description = "RouterOS version. Pick a release at least 2 weeks old."
  type        = string

  validation {
    condition     = can(regex("^7\\.[0-9]+(\\.[0-9]+)?$", var.chr_version))
    error_message = "chr_version must look like 7.25 or 7.25.1."
  }
}

variable "chr_arch" {
  description = "arm64 -> A1.Flex (chr_mode = dual-nic), x86_64 -> E2.1.Micro (chr_mode = single-nic)."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.chr_arch)
    error_message = "chr_arch must be arm64 or x86_64."
  }
}

variable "image_path" {
  description = "Local QCOW2 produced by prepare_image.sh (outside the repo)."
  type        = string
}

variable "image_sha256" {
  description = "SHA-256 of image_path as printed by prepare_image.sh. Upload is refused if the file differs."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.image_sha256))
    error_message = "image_sha256 must be a 64-char lowercase hex digest."
  }
}

variable "max_image_mib" {
  description = "Sanity cap on the QCOW2 size (Always Free Object Storage is 20 GB in total)."
  type        = number
  default     = 1024
}

variable "image_size_bytes" {
  description = "Size of image_path in bytes (printed by `stat -c %s`). Used only for the Always Free check."
  type        = number
}
