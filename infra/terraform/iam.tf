# iam.tf — Least-privilege, borrower-scoped service account for the B2 agent.
#
# General Principle map:
#   P-03 (least privilege / separation of duties): a single serving identity that gets only
#         the roles it needs (extract, ingest to A2, query peer data, call models + guardrail
#         + DLP, write audit + traces). No shared "kitchen-sink" SA.
#   P-05 (residency): the identity is project-scoped; data access is to in-region services.
#   CMEK explicit: the SA that touches CMEK-encrypted data gets its own cryptoKey binding.
#   R3 (borrower-scoped ACL): filings are ingested into A2 with borrower:<id> ACL tags; the
#         app reads only borrower-scoped principals. ACL enforcement lives in A2, but the
#         agent SA carries only the discoveryengine roles it needs.

resource "google_service_account" "app" {
  account_id   = "credit-memo-app"
  display_name = "B2 Credit-Memo Assistant (serving / API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Serving path: extract filings (Document AI), ingest + query the A2 governed RAG store,
  # read peer data (BigQuery), call models + DLP, write audit + traces, run evals, read
  # secrets. No org-wide writes.
  app_roles = [
    "roles/aiplatform.user",        # Gemini reasoning + Gen AI evals
    "roles/documentai.apiUser",     # process filings
    "roles/discoveryengine.editor", # ingest filings into A2 (borrower-scoped ACL)
    "roles/bigquery.dataViewer",    # read the peer-financials dataset
    "roles/bigquery.jobUser",       # run peer-comparison queries
    "roles/dlp.user",               # deidentifyContent (P-04, R1)
    "roles/logging.logWriter",      # write redacted audit events to WORM sink (R2)
    "roles/cloudtrace.agent",       # OpenTelemetry spans (content OFF)
    "roles/secretmanager.secretAccessor",
    "roles/run.invoker",
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# App uses the CMEK for envelope ops it performs directly.
resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.credit_memo.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}

# ------------------------- Agent Runtime identity --------------------------- #
resource "google_service_account" "agent_runtime" {
  account_id   = "credit-memo-runtime"
  display_name = "B2 Agent Runtime (reasoningEngine) identity"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "agent_runtime" {
  for_each = toset(["roles/aiplatform.user", "roles/logging.logWriter", "roles/cloudtrace.agent"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.agent_runtime.email}"
}
