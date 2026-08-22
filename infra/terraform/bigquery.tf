# bigquery.tf — The peer-financials dataset (PeerDataPort backend).
#
# General Principle map:
#   P-05 (residency): the dataset location is asia-southeast1, so peer financials stay
#         in-country.
#   P-09/CMEK: the dataset is encrypted with the regional CMEK key (kms.tf). Internal data
#         only; there is no public/HTTP surface to this dataset.
#
# The schema is the contract the BigQueryPeerDataAdapter queries: (sector, peer_name,
# metric, value). Peer rows are curated, fictional reference data, never borrower PII.

resource "google_bigquery_dataset" "credit_peers" {
  dataset_id  = "credit_peers"
  location    = var.region # asia-southeast1 — in-country (P-05)
  description = "Curated peer-financials reference data for the credit-memo peer comparison."

  default_encryption_configuration {
    kms_key_name = google_kms_crypto_key.credit_memo.id
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.bigquery,
  ]
}

resource "google_bigquery_table" "peer_financials" {
  dataset_id          = google_bigquery_dataset.credit_peers.dataset_id
  table_id            = "peer_financials"
  deletion_protection = true

  encryption_configuration {
    kms_key_name = google_kms_crypto_key.credit_memo.id
  }

  schema = jsonencode([
    { name = "sector", type = "STRING", mode = "REQUIRED" },
    { name = "peer_name", type = "STRING", mode = "REQUIRED" },
    { name = "metric", type = "STRING", mode = "REQUIRED" },
    { name = "value", type = "FLOAT", mode = "REQUIRED" },
    { name = "period", type = "STRING", mode = "NULLABLE" },
  ])
}
