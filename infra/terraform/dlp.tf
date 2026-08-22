# dlp.tf — Sensitive Data Protection / DLP inspect + deidentify templates (rule R1).
#
# General Principle map:
#   P-04 (PII redaction at the boundary): the redaction adapter (dlp_redaction) calls
#         deidentifyContent with these templates so borrower PII is removed BEFORE any text
#         is sent to the model, indexed into A2, written to the audit log, or put in a span.
#         Info types mirror RedactionFinding.info_type in domain/models.py.
#   P-05 (residency): both templates are created in asia-southeast1.
#
# Built-in info types covered: PERSON_NAME, EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD_NUMBER,
# IBAN_CODE, SWIFT_CODE. Plus a CUSTOM Singapore NRIC/FIN info type (SG_NRIC_FIN), the
# identifier a Singapore banking workload must scrub.
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/data_loss_prevention_inspect_template

locals {
  dlp_parent = "projects/${var.project_id}/locations/${var.region}"

  builtin_info_types = [
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
    "SWIFT_CODE",
  ]
}

# ----------------------------- Inspect template ----------------------------- #
resource "google_data_loss_prevention_inspect_template" "credit_memo" {
  parent       = local.dlp_parent
  display_name = "credit-memo-inspect"
  description  = "Detects PII in credit prompts/responses (incl. SG NRIC/FIN, bank codes)."

  inspect_config {
    dynamic "info_types" {
      for_each = local.builtin_info_types
      content {
        name = info_types.value
      }
    }

    # Custom SG NRIC/FIN: S/T/F/G/M + 7 digits + checksum letter.
    custom_info_types {
      info_type {
        name = "SG_NRIC_FIN"
      }
      likelihood = "LIKELY"
      regex {
        pattern = "[STFGM][0-9]{7}[A-Z]"
      }
    }

    min_likelihood = "POSSIBLE"
    include_quote  = false # never echo the matched PII back out (P-04)
  }
}

# --------------------------- Deidentify template ---------------------------- #
resource "google_data_loss_prevention_deidentify_template" "credit_memo" {
  parent       = local.dlp_parent
  display_name = "credit-memo-deidentify"
  description  = "Replaces detected PII with [INFO_TYPE] placeholders for safe logging."

  deidentify_config {
    info_type_transformations {
      transformations {
        dynamic "info_types" {
          for_each = local.builtin_info_types
          content {
            name = info_types.value
          }
        }
        primitive_transformation {
          replace_with_info_type_config = true # e.g. "John" -> "[PERSON_NAME]"
        }
      }

      transformations {
        info_types {
          name = "SG_NRIC_FIN"
        }
        primitive_transformation {
          replace_config {
            new_value {
              string_value = "[SG_NRIC_FIN]"
            }
          }
        }
      }
    }
  }
}
