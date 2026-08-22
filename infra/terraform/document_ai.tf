# document_ai.tf — Document AI processor for filing extraction (DocumentExtractionPort).
#
# General Principle map:
#   P-05 (residency): the processor is created in a regional location (asia-southeast1) so
#         a borrower's financial statements are parsed in-country, never in a global tier.
#   P-04 (minimise data to the model): extraction produces structured fields + text that is
#         redacted (DLP) before it reaches the model or the audit log.
#
# A form-parser processor is sufficient for financial statements, loan agreements and
# covenant certificates; swap the type for a custom/specialised processor as needed.

resource "google_document_ai_processor" "credit_memo" {
  location     = var.region # asia-southeast1 — in-country parsing (P-05)
  display_name = "credit-memo-extractor"
  type         = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
