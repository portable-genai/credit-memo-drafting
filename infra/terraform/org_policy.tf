# Project guardrails make the residency contract enforceable at deploy time: the allowed
# locations derive from the selected var.region.
resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # The deploy region and its sub-locations, plus `global` when this deployment runs
        # a grounded research panel (Vertex serves web grounding from the global endpoint
        # only). Admitting `global` is a statement about where a QUERY may go: every
        # resource this stack creates is still regional, and borrower evidence never
        # leaves the region. See var.allow_global_endpoints.
        #
        # var.resource_location_values overrides both, and widening it is a jurisdiction
        # statement rather than an exception list.
        allowed_values = length(var.resource_location_values) > 0 ? var.resource_location_values : concat(
          ["in:${var.region}-locations"],
          var.allow_global_endpoints ? ["is:global"] : [],
        )
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
