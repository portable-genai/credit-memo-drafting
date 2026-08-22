# Terraform: Doc2 Credit-Memo / Underwriting Assistant infrastructure

Managed-stack infrastructure for Doc2, defaulting to `asia-southeast1` (Singapore). Only
`project_id`, the residency values and a few genuinely per-tenant values (org/billing ids,
the VPC-SC toggle) are variables; every service identifier and template name is concrete and
every location derives from `var.region`, which is chosen at deploy time and validated against
the `allowed_regions` allowlist (default `["asia-southeast1"]`), because residency is a
control, not a preference.

The governed RAG store (Agent Search data stores) lives in **Hrz2**, not here. This stack
provisions Doc2's own resources: extraction, peer data, redaction, guardrail, audit, keys
and the serving identity.

## Files

| File | What it provisions |
| --- | --- |
| `providers.tf` | google + google-beta providers, pinned to the project and region |
| `variables.tf` | the only knobs (project_id, org_id, retention_days, VPC-SC toggle) |
| `apis.tf` | the managed services Doc2 uses (nothing speculative) |
| `kms.tf` | one regional CMEK key ring + per-service-agent key bindings |
| `document_ai.tf` | the Document AI form-parser processor (extraction) |
| `bigquery.tf` | the CMEK-encrypted peer-financials dataset + table |
| `dlp.tf` | DLP inspect + deidentify templates (incl. SG NRIC/FIN) |
| `model_armor.tf` | the Model Armor guardrail template (both directions) |
| `logging_worm.tf` | locked WORM audit bucket + sink + data-access audit config |
| `iam.tf` | least-privilege serving + Agent Runtime service accounts |
| `vpc_sc.tf` | the VPC Service Controls perimeter (residency / exfiltration) |
| `agent_runtime.tf` | the Agent Runtime staging bucket (CMEK) |
| `outputs.tf` | values to wire into `config/settings.yaml` after apply |

## Usage

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, org_id
terraform init
terraform plan
terraform apply
```

After apply, export the outputs into the runtime environment so they land in
`config/settings.yaml` via `${VAR}` interpolation (processor id, peer dataset, DLP
templates, KMS key, WORM bucket).

## Warnings

- **The WORM bucket lock is irreversible.** `locked = true` in `logging_worm.tf` permanently
  prevents reducing retention or deleting the bucket for the retention window. Confirm
  `retention_days` before apply.
- **VPC-SC blocks calls from outside the perimeter.** Follow the deploy-order caveat in
  `vpc_sc.tf`: apply with `enable_vpc_sc = false` first, add your CI/operator identity to an
  access level, then re-apply with it true.
- **CMEK does not cascade.** Each service that encrypts with the key has its own binding in
  `kms.tf`; adding a new CMEK-using resource means adding a new binding.

Do not run `terraform apply` against a shared project without reviewing the plan.
