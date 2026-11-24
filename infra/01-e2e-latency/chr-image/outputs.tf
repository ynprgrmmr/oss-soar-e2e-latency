output "chr_image_ocid" {
  description = "Set this as chr_image_ocid in ../terraform/terraform.tfvars."
  value       = oci_core_image.chr.id
}

output "chr_image_name" {
  value = oci_core_image.chr.display_name
}

output "compatible_shape" {
  value = oci_core_shape_management.chr.shape_name
}

output "source_object" {
  value = "${oci_objectstorage_bucket.images.name}/${oci_objectstorage_object.chr.object}"
}
