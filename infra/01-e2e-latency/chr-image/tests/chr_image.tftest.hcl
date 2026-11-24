# Offline tests (mock provider, no OCI calls). The fixture file stands in for
# a QCOW2 so the sha256 precondition can be exercised.

mock_provider "oci" {
  mock_data "oci_objectstorage_namespace" {
    defaults = { namespace = "mockns" }
  }

  mock_data "oci_core_compute_global_image_capability_schemas" {
    defaults = {
      compute_global_image_capability_schemas = [{ current_version_name = "mock-v1" }]
    }
  }
}

variables {
  oci_profile      = "DEFAULT"
  region           = "us-phoenix-1"
  compartment_ocid = "ocid1.compartment.oc1..lab"
  chr_version      = "7.25.1"
  chr_arch         = "arm64"
  image_path       = "tests/fixtures/fake.qcow2"
  image_sha256     = "02c154b1d267962d2c0c6472f1643c72b9245e711a4d8718475181110c64e874"
  image_size_bytes = 17
  max_image_mib    = 1024
}

run "arm64_imports_with_uefi_and_a1" {
  command = apply

  assert {
    condition     = oci_core_image.chr.launch_mode == "PARAVIRTUALIZED"
    error_message = "CHR should import as PARAVIRTUALIZED."
  }

  assert {
    condition     = oci_core_shape_management.chr.shape_name == "VM.Standard.A1.Flex"
    error_message = "arm64 image must be made compatible with A1.Flex."
  }

  assert {
    condition     = jsondecode(oci_core_compute_image_capability_schema.chr_uefi[0].schema_data["Compute.Firmware"]).defaultValue == "UEFI_64"
    error_message = "arm64 image must boot UEFI_64."
  }

  assert {
    condition     = oci_objectstorage_bucket.images.access_type == "NoPublicAccess"
    error_message = "Bucket must be private."
  }
}

run "x86_64_targets_micro_without_uefi_schema" {
  command   = apply
  state_key = "x86"

  variables {
    chr_arch = "x86_64"
  }

  assert {
    condition     = oci_core_shape_management.chr.shape_name == "VM.Standard.E2.1.Micro"
    error_message = "x86_64 image should target E2.1.Micro."
  }

  assert {
    condition     = length(oci_core_compute_image_capability_schema.chr_uefi) == 0
    error_message = "x86_64 image should not force UEFI."
  }
}

run "refuses_wrong_digest" {
  command   = plan
  state_key = "bad"

  variables {
    image_sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
  }

  expect_failures = [oci_objectstorage_object.chr]
}

run "flags_oversized_image" {
  command   = plan
  state_key = "big"

  variables {
    image_size_bytes = 2147483648
  }

  expect_failures = [check.always_free_object_storage]
}
