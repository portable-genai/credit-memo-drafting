# Analysis-bundle custody: a regional, CMEK-encrypted bucket whose lifecycle rule IS the
# retention guarantee.
#
# WHY THIS EXISTS AT ALL, and why it replaced three other things.
#
# This service holds one analysis at a time: the files a user uploaded for one question,
# the manifest of what was used, and the memo built from them. It holds nothing else and
# holds it for a fixed window the console prints to the user. That posture removed more
# infrastructure than it added:
#
#   * Agent Search (`discoveryengine`) is gone. It serves `global`, `us` and `eu` and no
#     Cloud region at all, so a standing index of borrower documents could not be held in
#     Singapore by any configuration. Retrieval is now per-request and in-process.
#   * The Document AI processor is gone. It routed borrower financials to the `us`
#     multi-region on the `rc` channel; Gemini reads the same PDFs in asia-southeast1.
#   * The WORM audit bucket is gone. A seven-year locked log is the right shape for a
#     system of record and the wrong shape for a demo that deletes its own evidence in
#     fifteen days. See `logging.tf` for what replaced it.
#
# What is left is one bucket. When no analysis is running it is empty, and an empty
# bucket costs nothing: that is the whole of the standing cost of this stack.
#
# The lifecycle rule is deliberately the enforcement point rather than application code.
# A sweep this service has to remember to run is a promise that breaks quietly the first
# time the service is not running; a lifecycle rule is kept by the storage layer whether
# or not anything is deployed.

resource "google_storage_bucket" "analysis_bundles" {
  name     = "${var.project_id}-credit-memo-analyses"
  project  = var.project_id
  location = var.region # asia-southeast1 — regional, not multi-region: the evidence stays in one country

  # No object may outlive the window the console promised the user. `num_newer_versions`
  # and `with_state` are deliberately absent: every object goes, including the manifest,
  # so an expired analysis leaves no trace of which borrower was assessed.
  lifecycle_rule {
    condition {
      age = var.analysis_retention_days
    }
    action {
      type = "Delete"
    }
  }

  # An upload that failed halfway must not linger past the window either.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 1
    }
    action {
      type = "Delete"
    }
  }

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Versioning off on purpose. A retained previous version is exactly the durable copy
  # this posture says does not exist.
  versioning {
    enabled = false
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.credit_memo.id
  }

  labels = {
    system    = "credit-memo-drafting"
    retention = "${var.analysis_retention_days}d"
    contains  = "borrower-evidence"
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}

# The service account reads and writes only inside this bucket. Object-level access
# control is the application's fail-closed subset ACL; this is the outer boundary.
resource "google_storage_bucket_iam_member" "analysis_bundles_rw" {
  bucket = google_storage_bucket.analysis_bundles.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

# Cloud Storage encrypts with the regional key on this project's behalf, so its service
# agent needs the key. Without this the bucket create fails with a permission error that
# names KMS rather than the bucket, which is a confusing way to learn about CMEK.
resource "google_kms_crypto_key_iam_member" "storage" {
  crypto_key_id = google_kms_crypto_key.credit_memo.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}
