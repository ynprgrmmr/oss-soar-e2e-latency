output "budget_id" {
  value = try(oci_budget_budget.lab[0].id, null)
}

output "budget_alert_rules" {
  value = { for k, r in oci_budget_alert_rule.lab : k => "${r.type} ${r.threshold}%" }
}

output "nightly_stop_schedule_id" {
  value = try(oci_resource_scheduler_schedule.nightly_stop[0].id, null)
}

output "nightly_stop_cron_utc" {
  value = var.enable_scheduler ? var.stop_cron_utc : null
}
