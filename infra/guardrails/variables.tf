variable "oci_profile" {
  type    = string
  default = "DEFAULT"
}

variable "region" {
  description = "Tenancy home region (us-phoenix-1 for this lab). Budget/IAM writes must target the home region."
  type        = string
}

variable "tenancy_ocid" {
  description = "Root compartment OCID. Budgets must be created in the root compartment."
  type        = string
}

variable "compartment_ocid" {
  description = "Lab compartment watched by the budget and stopped by the scheduler."
  type        = string
}

variable "project" {
  type    = string
  default = "soar-net-lab"
}

# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
variable "enable_budget" {
  type    = bool
  default = true
}

variable "budget_amount" {
  description = "Monthly budget in the tenancy's billing currency (e.g. JPY). Keep tiny: the lab should cost 0."
  type        = number
  default     = 100

  validation {
    condition     = var.budget_amount > 0
    error_message = "budget_amount must be > 0."
  }
}

variable "budget_alert_recipients" {
  description = "Comma-separated e-mail addresses. Set only in terraform.tfvars (git-ignored)."
  type        = string
  sensitive   = true
}

variable "budget_alert_rules" {
  description = "Alert rules. type = ACTUAL | FORECAST, threshold in percent of budget_amount."
  type = map(object({
    type      = string
    threshold = number
  }))
  default = {
    actual-any  = { type = "ACTUAL", threshold = 1 }
    actual-full = { type = "ACTUAL", threshold = 100 }
    forecast    = { type = "FORECAST", threshold = 100 }
  }

  validation {
    condition     = alltrue([for r in values(var.budget_alert_rules) : contains(["ACTUAL", "FORECAST"], r.type) && r.threshold > 0])
    error_message = "Each rule needs type ACTUAL|FORECAST and threshold > 0."
  }
}

# ---------------------------------------------------------------------------
# Resource Scheduler (nightly stop)
# ---------------------------------------------------------------------------
variable "enable_scheduler" {
  type    = bool
  default = true
}

variable "stop_cron_utc" {
  description = "Cron expression (UTC). Default 15:00 UTC = 24:00 JST."
  type        = string
  default     = "0 15 * * *"
}

variable "create_scheduler_policy" {
  description = "Create the IAM policy that lets the schedule stop instances. Requires IAM admin rights in policy_compartment_ocid."
  type        = bool
  default     = true
}

variable "policy_compartment_ocid" {
  description = "Where the scheduler IAM policy is attached. Defaults to the lab compartment."
  type        = string
  default     = null
}
