terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0, < 8.0.0"
    }
  }
}

# Auth is read from ~/.oci/config (profile below), so no key material
# ever lands in *.tfvars or state inputs.
provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.region
}
