# Cost guardrails that must OUTLIVE individual experiment stacks.
# Kept in a separate Terraform root/state so `terraform destroy` of an
# experiment never removes the budget or the nightly stop schedule.

locals {
  tags = {
    "project"    = var.project
    "managed-by" = "terraform"
    "stack"      = "guardrails"
  }
}

# ---------------------------------------------------------------------------
# Budget scoped to the lab compartment (resource lives in root compartment)
# ---------------------------------------------------------------------------
resource "oci_budget_budget" "lab" {
  count = var.enable_budget ? 1 : 0

  compartment_id = var.tenancy_ocid
  target_type    = "COMPARTMENT"
  targets        = [var.compartment_ocid]
  amount         = var.budget_amount
  reset_period   = "MONTHLY"
  display_name   = "${var.project}-lab-budget"
  description    = "soar-net-lab: expected spend is 0 (Always Free). Any alert = investigate."
  freeform_tags  = local.tags
}

resource "oci_budget_alert_rule" "lab" {
  for_each = var.enable_budget ? var.budget_alert_rules : {}

  budget_id      = oci_budget_budget.lab[0].id
  display_name   = "${var.project}-${each.key}"
  type           = each.value.type
  threshold      = each.value.threshold
  threshold_type = "PERCENTAGE"
  recipients     = var.budget_alert_recipients
  message        = "soar-net-lab budget alert (${each.key}). Check for non-Always-Free resources and run terraform destroy."
  freeform_tags  = local.tags
}

# ---------------------------------------------------------------------------
# Nightly STOP of every instance in the lab compartment
#
# Resource Scheduler filters support DEFINED tags only (not the freeform
# `auto-stop` tag used by the experiment stacks), so the filter is the
# dedicated lab compartment itself. Keep non-lab resources out of it.
# ---------------------------------------------------------------------------
resource "oci_resource_scheduler_schedule" "nightly_stop" {
  count = var.enable_scheduler ? 1 : 0

  compartment_id     = var.compartment_ocid
  display_name       = "${var.project}-nightly-stop"
  description        = "Safety net: stop all lab instances nightly. Start manually when experimenting."
  action             = "STOP_RESOURCE"
  recurrence_type    = "CRON"
  recurrence_details = var.stop_cron_utc
  freeform_tags      = local.tags

  resource_filters {
    attribute                         = "COMPARTMENT_ID"
    should_include_child_compartments = false

    value {
      value = var.compartment_ocid
    }
  }
}

# The schedule acts as its own principal and needs permission to stop
# instances. Scoped to this one schedule and this one compartment.
resource "oci_identity_policy" "scheduler" {
  count = var.enable_scheduler && var.create_scheduler_policy ? 1 : 0

  compartment_id = coalesce(var.policy_compartment_ocid, var.compartment_ocid)
  name           = "${var.project}-resource-scheduler"
  description    = "Allow the soar-net-lab nightly-stop schedule to stop lab instances"
  freeform_tags  = local.tags

  statements = [
    "Allow any-user to manage instance-family in compartment id ${var.compartment_ocid} where all {request.principal.type='resourceschedule', request.principal.id='${oci_resource_scheduler_schedule.nightly_stop[0].id}'}",
  ]
}
