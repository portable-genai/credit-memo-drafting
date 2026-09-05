# variables.tf — The only knobs. Everything else is a concrete in-region value.
#
# General Principle map:
#   P-05 (residency): `region` is SELECTED AT DEPLOY TIME and validated against the
#         residency allowlist (var.allowed_regions) so a caller fails fast rather than
#         deploying to an unvetted, out-of-jurisdiction region. The default is
#         asia-southeast1 (Singapore).
#   P-07 (auditability/retention): `retention_days` is a Terraform variable (the WORM
#         bucket lock is irreversible, so retention must be deliberate).
#
# Per the build contract, ONLY project_id and a couple of genuinely per-tenant values
# (org/billing ids, the VPC-SC toggle) are variables. All service identifiers, locations
# and template names are concrete. The governed RAG store lives in A2, not here.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, Singapore-resident."
  type        = string
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allowlist: the regions this regulated stack may be deployed to. The region is
    chosen at deploy time (var.region) and validated against this list to FAIL FAST (P-05),
    so an operator cannot accidentally deploy to an unvetted region. Extending this list is
    the deliberate residency review point: do it only after confirming the full managed stack
    (DLP, Model Armor, Vertex/Agent Platform, CMEK, Logging) and your
    residency obligations are satisfied in that region.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1 (Singapore) but
    is overridable. Validated against var.allowed_regions so an unapproved region fails fast
    at `terraform plan` rather than deploying data out of jurisdiction (P-05).
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9). Fails at plan time = setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allowlist). Add it there first if that region is approved for this workload (P-05)."
  }
}

variable "zone" {
  description = "Default zone for zonal resources. Must sit inside var.region."
  type        = string
  default     = "asia-southeast1-a"
}

variable "analysis_retention_days" {
  description = <<-EOT
    How long an analysis and the evidence it used survive, in days.

    This is the number the console prints to the user ("available until ..."), and the
    bucket's lifecycle rule is what keeps the promise. It must equal
    `analysis_bundle.retention_days` in config/settings.yaml: the application states the
    window and the storage layer enforces it, and if the two disagree the application is
    lying to the user. `terraform test` asserts they match.

    This service is not a system of record. It holds one analysis at a time so that a
    user brings the evidence to each question and can see exactly what was used; a long
    window would quietly turn it into the document store it is deliberately not.
  EOT
  type        = number
  default     = 15

  validation {
    condition     = var.analysis_retention_days >= 1 && var.analysis_retention_days <= 90
    error_message = <<-EOT
      analysis_retention_days must be between 1 and 90. Below 1 a lifecycle rule cannot be
      expressed; above 90 this stops being a per-analysis window and becomes a document
      store, which needs the retention, deletion and personal-data decisions this
      deployment posture explicitly does not make.
    EOT
  }
}

variable "org_id" {
  description = "Organization id — required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used by Assured Workloads / FinOps tagging)."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
    Create once per org with:
      gcloud access-context-manager policies create \
        --organization=ORG_ID --title="sg-residency"
  EOT
  type        = string
  default     = ""
}

variable "vpc_network_name" {
  description = "Name of the VPC that hosts the private service endpoints for the agent."
  type        = string
  default     = "credit-memo-vpc"
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI/data APIs (P-05)."
  type        = bool
  default     = true
}

variable "resource_location_values" {
  description = <<-EOT
    Value groups for the gcp.resourceLocations Org Policy.

    Empty (the default) derives the strictest form from the deploy region: that region and
    its sub-locations, nothing else. Every resource this stack CREATES fits inside it. The
    analysis bundle is a regional bucket and the key ring is regional; the Agent Search
    data store, the Document AI processor and the BigQuery peer dataset that used to force
    a wider boundary are all gone.

    `global` is admitted for grounded model calls, deliberately and as a recorded
    deviation. Vertex serves web grounding only from the global endpoint, so an analyst
    research panel means a call whose search leg is processed outside the deploy region.
    That is a decision about where a QUERY goes, not about where borrower evidence lives:
    the uploaded documents, the bundle, the memo and the audit trail all stay in region,
    and grounded results never enter the memo, the export or any engine input. Record the
    deviation in org-metadata/docs/deployment-posture.md, not only here.

    Widen further ONLY to a value group that still describes ONE JURISDICTION
    (`in:us-locations` keeps everything inside the United States). NEVER list an individual
    foreign region to unblock one service: that turns a jurisdiction boundary into a list
    of exceptions nobody can reason about.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for value in var.resource_location_values : startswith(value, "in:") || startswith(value, "is:")])
    error_message = "Each value must be an Org Policy location value group (in:...) or a literal location (is:...)."
  }
}

variable "allow_global_endpoints" {
  description = <<-EOT
    Admit `global` to the gcp.resourceLocations allowlist.

    Required for Vertex web grounding, which is served from the global endpoint only. Set
    false for a deployment that runs no grounded research panel and wants the strictest
    possible boundary.

    What this does and does not permit is the whole point. It permits a model call whose
    search leg leaves the region. It does not move any stored data: the analysis bundle
    and the keys stay regional by their own configuration, and no resource in this stack is
    created in `global`.
  EOT
  type        = bool
  default     = true
}

