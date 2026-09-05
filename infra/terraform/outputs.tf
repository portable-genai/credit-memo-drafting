# outputs.tf — Values the app/operators need to wire settings.yaml after apply.
#
# These map 1:1 onto config/settings.yaml / config.py fields so a deploy is just
# "apply, then export these into the runtime environment".

output "project_id" {
  description = "The deployment project id."
  value       = var.project_id
}

output "region" {
  description = "Deployment region selected at deploy time (default asia-southeast1, Singapore)."
  value       = var.region
}

# --------------------------------- KMS -------------------------------------- #
output "kms_key" {
  description = "Regional CMEK crypto key id (settings.yaml kms_key / CREDIT_MEMO_KMS_KEY)."
  value       = google_kms_crypto_key.credit_memo.id
}

# ------------------------------- WORM logging ------------------------------- #

# ------------------------- Model Armor / DLP -------------------------------- #
output "model_armor_template" {
  description = "Model Armor template id (settings.yaml model_armor.template_id)."
  value       = google_model_armor_template.credit_memo_guardrail.template_id
}

output "dlp_inspect_template" {
  description = "DLP inspect template (settings.yaml dlp.inspect_template)."
  value       = google_data_loss_prevention_inspect_template.credit_memo.id
}

output "dlp_deidentify_template" {
  description = "DLP deidentify template (settings.yaml dlp.deidentify_template)."
  value       = google_data_loss_prevention_deidentify_template.credit_memo.id
}

# ----------------------------- Service accounts ----------------------------- #
output "app_service_account" {
  description = "Serving/API service account email."
  value       = google_service_account.app.email
}

output "agent_runtime_service_account" {
  description = "Agent Runtime (reasoningEngine) service account email."
  value       = google_service_account.agent_runtime.email
}

output "agent_staging_bucket" {
  description = "Agent Runtime staging bucket for the SDK-based deploy."
  value       = google_storage_bucket.agent_staging.name
}

# --------------------------- Analysis bundles ------------------------------- #
output "analysis_bundle_bucket" {
  description = "Bucket holding one analysis at a time (settings.yaml analysis_bundle.bucket)."
  value       = google_storage_bucket.analysis_bundles.name
}

output "analysis_retention_days" {
  description = <<-EOT
    The window the console promises the user, enforced by the bucket's lifecycle rule.
    Must equal analysis_bundle.retention_days in config/settings.yaml.
  EOT
  value       = var.analysis_retention_days
}
