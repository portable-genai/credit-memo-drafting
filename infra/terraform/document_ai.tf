# document_ai.tf — Document AI processor for filing extraction (DocumentExtractionPort).
#
# General Principle map:
#   P-05 (residency): PARTIAL, and stated rather than absorbed. The processor is created at
#         var.docai_location, which defaults to the `us` MULTI-REGION -- so a borrower's
#         financial statements are parsed in the United States while the rest of the stack
#         stays in Singapore. It is never a GLOBAL tier: `us` names one jurisdiction. Document
#         AI serves asia-southeast1 only once Google grants single-region access; set
#         var.docai_location (and CREDIT_MEMO_DOCAI_LOCATION) to asia-southeast1 when it does.
#   P-04 (minimise data to the model): extraction produces structured fields + text that is
#         redacted (DLP) before it reaches the model or the audit log.
#
# A form-parser processor is sufficient for financial statements, loan agreements and
# covenant certificates; swap the type for a custom/specialised processor as needed.

resource "google_document_ai_processor" "credit_memo" {
  location     = var.docai_location # NOT var.region: Document AI serves neither every region nor, yet, ours in-country
  display_name = "credit-memo-extractor"
  type         = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
