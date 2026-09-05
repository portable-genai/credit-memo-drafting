# providers.tf — Provider pinning for the B2 Credit-Memo / Underwriting Assistant.
#
# General Principle map:
#   P-05 (data residency / in-country): every provider call is pinned to the Singapore
#         region (var.region, default asia-southeast1). There is no global/multi-region default.
#   P-02 (no lock-in): Terraform is the only place infra is described; the app itself
#         talks to ports, not these resources.
#
# google-beta is required because several sovereignty resources (Model Armor templates,
# Assured Workloads, some Access Context Manager fields) are only exposed on the beta
# surface as of the pinned provider line.

terraform {
  required_version = ">= 1.9.0"

  # Partial backend: the bucket and the per-installation prefix are supplied at init, which
  # keeps the module reusable while making accidental local state impossible in a named
  # deployment. Local state for a stack that owns KMS keys and an org policy is state that
  # exists on exactly one laptop.
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0" # 6.x line — current GA surface (mid-2026)
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }
}

# Primary (GA) provider — every resource defaults to Singapore.
provider "google" {
  project = var.project_id
  region  = var.region # allowlisted deploy-time region, regional, never global
}

# Beta provider — same project/region, used only where a resource needs it.
provider "google-beta" {
  project = var.project_id
  region  = var.region
}
