# Audit logging without a WORM bucket, and why that is the right shape here.
#
# This stack used to create a Cloud Logging bucket with `locked = true` and 2557 days
# (~7 years) of irreversible retention, plus a sink routing the application's audit
# events into it. That is the correct shape for a system of record: the log outlives the
# thing it describes, and nobody -- including a project owner -- can shorten it.
#
# It is the wrong shape for this service. An analysis and every file in it are deleted
# after `analysis_retention_days`, so a seven-year locked log would preserve, for seven
# years, a detailed account of borrower assessments whose evidence the deployment
# promised to delete in fifteen days. The log would outlive its own subject by a factor
# of a hundred and seventy, and no user reading "available until 20 September" would
# expect that.
#
# So the audit trail lives in the project's own `_Default` log bucket at Google's default
# retention, which the operator can set to whatever their policy requires. The
# application still writes the same redacted audit events (`roles/logging.logWriter` in
# iam.tf); nothing about what is recorded changed. What changed is that this stack no
# longer takes an irreversible seven-year decision on an operator's behalf for a service
# that is deliberately not a system of record.
#
# An adopter running this as a system of record should restore the locked bucket and the
# sink, and should raise `analysis_retention_days` to match -- in that order, because a
# locked bucket cannot be undone if the second half turns out to be wrong.
#
# Data-access logging stays on: it is what shows who read whose evidence, which is the
# question a reviewer actually asks of a service that holds borrower documents.

# Authoritative for the service it names, which is the whole point and also the hazard: it
# REPLACES the project's audit config for `allServices` rather than adding to it. In a
# project where another stack already enables ADMIN_READ, applying this silently drops it,
# and Terraform reports the whole thing as a harmless create because this stack has no prior
# state for a resource that is nonetheless already live. Audit coverage going backwards is
# not something a deployment should be able to do by saying nothing.
resource "google_project_iam_audit_config" "data_access" {
  count   = var.manage_audit_config ? 1 : 0
  project = var.project_id
  service = "allServices"

  audit_log_config {
    log_type = "DATA_READ"
  }

  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
