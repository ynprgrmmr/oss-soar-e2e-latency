# Import a MikroTik CHR QCOW2 as an OCI custom image in the lab compartment.
#
#   prepare_image.sh (local)  ->  bucket/object  ->  oci_core_image (PARAVIRTUALIZED)
#     arm64 : + UEFI_64 firmware capability + A1.Flex shape compatibility
#     x86_64: + E2.1.Micro shape compatibility
#
# Separate root/state from the experiment stack so `terraform destroy` of the
# VMs does not delete the (slow to rebuild) image.

locals {
  is_arm      = var.chr_arch == "arm64"
  object_name = "mikrotik-chr-${var.chr_version}-${var.chr_arch}.qcow2"
  shape       = local.is_arm ? "VM.Standard.A1.Flex" : "VM.Standard.E2.1.Micro"

  tags = {
    "project"     = var.project
    "managed-by"  = "terraform"
    "stack"       = "chr-image"
    "chr-version" = var.chr_version
    "chr-arch"    = var.chr_arch
  }
}

data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.compartment_ocid
}

resource "oci_objectstorage_bucket" "images" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = var.bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags  = local.tags
}

resource "oci_objectstorage_object" "chr" {
  namespace    = data.oci_objectstorage_namespace.ns.namespace
  bucket       = oci_objectstorage_bucket.images.name
  object       = local.object_name
  source       = var.image_path
  content_type = "application/octet-stream"

  # A changed file (new digest) forces a re-upload.
  metadata = {
    "sha256" = var.image_sha256
  }

  lifecycle {
    precondition {
      condition     = fileexists(var.image_path) && filesha256(var.image_path) == var.image_sha256
      error_message = "image_path does not match image_sha256. Re-run prepare_image.sh and update terraform.tfvars."
    }
  }
}

resource "oci_core_image" "chr" {
  compartment_id = var.compartment_ocid
  display_name   = "mikrotik-chr-${var.chr_version}-${var.chr_arch}"
  launch_mode    = "PARAVIRTUALIZED"
  freeform_tags  = local.tags

  image_source_details {
    source_type              = "objectStorageTuple"
    namespace_name           = data.oci_objectstorage_namespace.ns.namespace
    bucket_name              = oci_objectstorage_bucket.images.name
    object_name              = oci_objectstorage_object.chr.object
    source_image_type        = "QCOW2"
    operating_system         = "MikroTik RouterOS"
    operating_system_version = var.chr_version
  }

  timeouts {
    create = "60m"
  }
}

# Arm images must boot with UEFI. Capability schemas are versioned against
# the global schema published by OCI.
data "oci_core_compute_global_image_capability_schemas" "global" {
  count = local.is_arm ? 1 : 0
}

resource "oci_core_compute_image_capability_schema" "chr_uefi" {
  count = local.is_arm ? 1 : 0

  compartment_id = var.compartment_ocid
  image_id       = oci_core_image.chr.id
  display_name   = "mikrotik-chr-${var.chr_version}-uefi"
  compute_global_image_capability_schema_version_name = (
    data.oci_core_compute_global_image_capability_schemas.global[0].compute_global_image_capability_schemas[0].current_version_name
  )

  schema_data = {
    "Compute.Firmware" = jsonencode({
      descriptorType = "enumstring"
      source         = "IMAGE"
      defaultValue   = "UEFI_64"
      values         = ["UEFI_64"]
    })
  }
}

resource "oci_core_shape_management" "chr" {
  compartment_id = var.compartment_ocid
  image_id       = oci_core_image.chr.id
  shape_name     = local.shape

  depends_on = [oci_core_compute_image_capability_schema.chr_uefi]
}

# ---------------------------------------------------------------------------
# Always Free fit (warning only)
# ---------------------------------------------------------------------------
check "always_free_object_storage" {
  assert {
    condition     = var.image_size_bytes <= var.max_image_mib * 1024 * 1024
    error_message = "QCOW2 is larger than max_image_mib; check the image before uploading (Always Free Object Storage = 20 GB total)."
  }

  assert {
    condition     = oci_objectstorage_bucket.images.access_type == "NoPublicAccess" && oci_objectstorage_bucket.images.storage_tier == "Standard"
    error_message = "Bucket must stay private and Standard tier."
  }
}
