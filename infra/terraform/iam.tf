# iam.tf — Least-privilege, borrower-scoped service account for the B2 agent.
#
# General Principle map:
#   P-03 (least privilege / separation of duties): a single serving identity that gets only
#         the roles it needs (extract, ingest to A2, query peer data, call models + guardrail
#         + DLP, write audit + traces). No shared "kitchen-sink" SA.
#   P-05 (residency): the identity is project-scoped; data access is to in-region services.
#   CMEK explicit: the SA that touches CMEK-encrypted data gets its own cryptoKey binding.
#   R3 (borrower-scoped ACL): uploaded evidence carries borrower:<id> ACL tags inside the
#         analysis bundle, and the application enforces the fail-closed subset check on
#         every read. The SA's bucket-level role is the outer boundary only.

resource "google_service_account" "app" {
  account_id   = "credit-memo-app"
  display_name = "B2 Credit-Memo Assistant (serving / API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Serving path: hold one analysis bundle, call models + DLP, write audit + traces, run
  # evals, read secrets. No org-wide writes.
  #
  # documentai.apiUser and discoveryengine.editor are gone with the services themselves:
  # extraction is Gemini reading the uploaded PDF in-region, and retrieval is per-request
  # and in-process, so there is no processor to call and no index to write to. The two
  # BigQuery roles went the same way: peer figures are now read from the filings the peers
  # themselves published, so there is no dataset to grant access to.
  app_roles = [
    "roles/aiplatform.user", # Gemini reasoning + Gen AI evals
    "roles/dlp.user",        # deidentifyContent / inspectContent (P-04, R1)
    # ...and the role that lets it READ the templates it is configured with. `dlp.user`
    # grants the CALL and not `dlp.inspectTemplates.get`, so a serving identity holding only
    # `dlp.user` can ask DLP to redact and cannot fetch the template that says HOW. The
    # sibling app found this on its own first managed deployment and this one repeated it
    # exactly: every build returned 500 with `dlp.inspectTemplates.get` denied on a template
    # that exists, at the very first pipeline step.
    "roles/dlp.reader",
    # Model Armor's screening call is a permission ON THE TEMPLATE
    # (`modelarmor.templates.useToSanitizeUserPrompt`), not a general API grant, so a
    # serving identity that can reach Vertex and DLP is still refused by the guardrail --
    # which is the step that runs before any retrieval or drafting, so the whole pipeline
    # returns 500 at its second step. The sibling app grants the same role for the same
    # reason.
    "roles/modelarmor.user",
    "roles/logging.logWriter", # write redacted audit events (R2)
    "roles/cloudtrace.agent",  # OpenTelemetry spans (content OFF)
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

# --------------------- Embedding host's runtime identity -------------------- #
# A portal that mounts this console same-origin runs it under a service account of the
# PORTAL's making. That identity is the one the container actually authenticates as, so
# without these grants the deployed app starts, authenticates, and then fails on its first
# CMEK read or model call -- which reads as a broken application rather than as a missing
# binding. Empty by default: an app deployed on its own needs none of this.
resource "google_project_iam_member" "additional_serving" {
  for_each = {
    for pair in setproduct(var.additional_serving_service_accounts, local.app_roles) :
    "${pair[0]}|${pair[1]}" => { email = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${each.value.email}"
}

resource "google_kms_crypto_key_iam_member" "additional_serving" {
  for_each      = toset(var.additional_serving_service_accounts)
  crypto_key_id = google_kms_crypto_key.credit_memo.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${each.value}"
}
