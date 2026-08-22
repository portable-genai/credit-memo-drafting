# Project guardrails make the residency contract enforceable at deploy time: the allowed
# locations derive from the selected var.region.
resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        allowed_values = ["in:${var.region}-locations"]
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
