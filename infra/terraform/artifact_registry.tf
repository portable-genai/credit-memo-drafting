# artifact_registry.tf — the registry this stack's own images are promoted into.
#
# General Principle map:
#   P-02 (no lock-in): Terraform is the only place infrastructure is described, so the
#         registry a deployment pulls from is not a resource that exists because somebody
#         once ran a gcloud command.
#   P-03 (residency): regional, pinned to var.region like every other resource here.
#   P-09 (CMEK explicit): a container image carries the application and its configuration,
#         which is customer material, so the repository is bound to the same key as the rest
#         of the stack. CMEK does not cascade, hence the explicit grant below.

# The Artifact Registry service agent does not exist until it is asked for, and a CMEK
# repository cannot be created before it holds the key grant. Creating the identity makes
# the ordering explicit rather than a race.
resource "google_project_service_identity" "artifactregistry" {
  provider = google-beta
  project  = var.project_id
  service  = "artifactregistry.googleapis.com"

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key_iam_member" "artifactregistry" {
  crypto_key_id = google_kms_crypto_key.credit_memo.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_project_service_identity.artifactregistry.email}"
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "credit-memo"
  description   = "Promoted Doc2 credit-memo API and console images, CMEK-encrypted."
  format        = "DOCKER"

  kms_key_name = google_kms_crypto_key.credit_memo.id

  # Immutable tags: a promoted release tag must always name the same bytes. Without this a
  # digest-pinned deployment can still be undermined by the tag that produced it being moved
  # under a reviewer who checked the tag rather than the digest.
  docker_config {
    immutable_tags = true
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.artifactregistry,
  ]
}
