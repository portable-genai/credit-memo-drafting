# vpc_sc.tf — VPC Service Controls perimeter around the AI/data plane.
#
# General Principle map:
#   P-05 (residency + exfiltration control): a service perimeter draws a logical boundary
#         around the sovereignty-critical APIs (Vertex/Agent Platform, DLP, Model Armor,
#         Logging, KMS, Secret Manager, Storage). Borrower data cannot be read across the
#         boundary to a non-Singapore project, which is what stops the filings and audit
#         log from leaving the country.
#   P-01 (least surface): only the services B2 uses are inside the perimeter.
#
# WHAT THE PERIMETER DOES NOT COVER:
#   A service perimeter governs Google APIs. Two legs of this service reach the public
#   internet instead, and neither is inside it:
#     * peer data (data.sec.gov / www.sec.gov). No borrower identity is sent: company
#       resolution matches a downloaded ticker file in-process, and the only borrower
#       attribute that reaches SEC is the SIC code — a public industry classification —
#       used to select the cohort. Everything after that is other companies' CIKs.
#     * web research, when CREDIT_MEMO_RESEARCH_ENABLED is set. That leg does send the
#       borrower's public identity, and is the recorded residency deviation.
#   Both are read-only and neither carries an uploaded document, a spread, a memo or an
#   audit record, all of which stay in region.
#
# Guarded by var.enable_vpc_sc so non-prod/dev applies can skip it (count = 0).
#
# DEPLOY-ORDER CAVEAT:
#   The perimeter blocks API calls from outside it. If you enable this BEFORE the resources
#   in the other files are created (or before your Terraform runner / CI identity is added
#   to the perimeter's access levels), those API calls will be denied and the apply will
#   fail. Recommended order:
#     1. Apply everything with enable_vpc_sc = false.
#     2. Add your operator/CI identity to an access level.
#     3. Re-apply with enable_vpc_sc = true to enforce the boundary.
#   # verify: VPC-SC dry-run mode before enforcing.

locals {
  perimeter_restricted_services = [
    "aiplatform.googleapis.com",
    "dlp.googleapis.com",
    "modelarmor.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ]
}

resource "google_access_context_manager_service_perimeter" "credit_memo" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/credit_memo_sg"
  title  = "credit_memo_sg"

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  status {
    resources           = ["projects/${data.google_project.this.number}"]
    restricted_services = local.perimeter_restricted_services

    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = local.perimeter_restricted_services
    }
  }

  depends_on = [google_project_service.required]
}
