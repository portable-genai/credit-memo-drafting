# Project guardrails make the residency contract enforceable at deploy time: the allowed
# locations derive from the selected var.region.
resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # var.resource_location_values overrides this only where a required service has no
        # single-region presence (Agent Search has none at all; Document AI has none until
        # in-region access is granted). See that variable: widening is a jurisdiction
        # statement, not an exception list.
        allowed_values = length(var.resource_location_values) > 0 ? var.resource_location_values : ["in:${var.region}-locations"]
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_org_policy_policy" "disable_service_account_keys" {
  name   = "projects/${var.project_id}/policies/iam.disableServiceAccountKeyCreation"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}
