# Offline plan tests: `terraform test` with a mocked provider. No cloud calls.

mock_provider "oci" {}

variables {
  region                  = "us-phoenix-1"
  tenancy_ocid            = "ocid1.tenancy.oc1..test"
  compartment_ocid        = "ocid1.compartment.oc1..lab"
  budget_alert_recipients = "ops@example.com"

  # Pin everything a local (git-ignored) terraform.tfvars might override,
  # so the tests are hermetic.
  oci_profile             = "DEFAULT"
  budget_amount           = 100
  enable_budget           = true
  enable_scheduler        = true
  create_scheduler_policy = true
  stop_cron_utc           = "0 15 * * *"
}

run "defaults_create_budget_scheduler_and_policy" {
  command = plan

  assert {
    condition     = oci_budget_budget.lab[0].compartment_id == var.tenancy_ocid
    error_message = "Budget must live in the root compartment."
  }

  assert {
    condition     = oci_budget_budget.lab[0].targets == tolist([var.compartment_ocid])
    error_message = "Budget must target the lab compartment."
  }

  assert {
    condition     = length(oci_budget_alert_rule.lab) == 3
    error_message = "Expected 3 default alert rules."
  }

  assert {
    condition     = oci_resource_scheduler_schedule.nightly_stop[0].action == "STOP_RESOURCE"
    error_message = "Schedule must stop, never terminate."
  }

  assert {
    condition     = oci_resource_scheduler_schedule.nightly_stop[0].recurrence_details == "0 15 * * *"
    error_message = "Default stop time should be 15:00 UTC."
  }

  assert {
    condition     = length(oci_identity_policy.scheduler) == 1
    error_message = "Scheduler policy should be created by default."
  }
}

run "everything_disabled" {
  command = plan

  variables {
    enable_budget    = false
    enable_scheduler = false
  }

  assert {
    condition     = length(oci_budget_budget.lab) == 0 && length(oci_budget_alert_rule.lab) == 0
    error_message = "Budget resources should be absent."
  }

  assert {
    condition     = length(oci_resource_scheduler_schedule.nightly_stop) == 0 && length(oci_identity_policy.scheduler) == 0
    error_message = "Scheduler resources should be absent."
  }
}

run "rejects_bad_alert_type" {
  command = plan

  variables {
    budget_alert_rules = { bad = { type = "SOMETIMES", threshold = 10 } }
  }

  expect_failures = [var.budget_alert_rules]
}
