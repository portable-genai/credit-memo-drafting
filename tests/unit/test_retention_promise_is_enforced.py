"""The retention window the console prints must be the one the storage layer keeps.

This deployment tells a user "available until 20 September, then deleted". Two separate
things have to agree for that sentence to be true: the application, which states the date
and prints it, and the bucket's lifecycle rule, which is what actually deletes anything.
If they drift, the application is lying to the user in whichever direction the drift went
— evidence gone before the memo could be reviewed, or evidence still sitting there long
after the deployment promised it would not be.

Nothing catches that drift at runtime. A lifecycle rule is invisible to the service, and
the service's number is invisible to Terraform. So it is caught here, by reading both.

The Document AI residency-deviation test this file replaces guarded the previous
posture's one honest compromise (bytes extracted in the `us` multi-region). That
processor is gone — text extraction is pypdf over the uploaded bytes, in-process — so the
deviation it guarded no longer exists. This guards the promise that took its place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from credit_memo.config import AnalysisBundleSettings, Settings

REPO = Path(__file__).resolve().parents[2]
TERRAFORM = REPO / "infra" / "terraform"


def _code(path: Path) -> str:
    """A Terraform file with its comments stripped.

    Every one of these files explains at length what it no longer provisions and why, so
    a check that reads the raw text finds the retired thing described in prose and calls
    it present. What matters is the HCL.
    """
    lines = [line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    return "\n".join(line for line in lines if line.strip())


def _terraform_default(variable: str) -> int:
    """The default of a numeric Terraform variable, read from the source."""
    body = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
    block = re.search(rf'variable "{re.escape(variable)}" \{{(.*?)\n\}}', body, re.S)
    assert block, f"variable {variable!r} is not declared in variables.tf"
    default = re.search(r"^\s*default\s*=\s*(\d+)", block.group(1), re.M)
    assert default, f"variable {variable!r} declares no numeric default"
    return int(default.group(1))


def test_the_console_and_the_bucket_agree_on_the_window() -> None:
    settings = yaml.safe_load((REPO / "config" / "settings.yaml").read_text(encoding="utf-8"))
    stated = int(settings["analysis_bundle"]["retention_days"])
    enforced = _terraform_default("analysis_retention_days")
    assert stated == enforced, (
        f"the console promises {stated} days and the bucket lifecycle rule deletes at "
        f"{enforced}. Whichever is longer, a user is being told something untrue about "
        "when their evidence disappears."
    )


def test_the_bucket_actually_carries_a_delete_rule_for_that_window() -> None:
    """A retention variable nothing reads is a number in a file, not a guarantee."""
    body = (TERRAFORM / "analysis_bundle.tf").read_text(encoding="utf-8")
    assert "google_storage_bucket" in body
    assert "var.analysis_retention_days" in body, (
        "the bucket does not reference the retention variable, so the window is enforced by nothing"
    )
    assert re.search(r"action\s*\{\s*type\s*=\s*\"Delete\"", body), (
        "the lifecycle rule does not delete; a rule that only changes storage class keeps "
        "the evidence forever at a lower price"
    )


def test_versioning_is_off_so_a_deleted_object_is_deleted() -> None:
    """A retained previous version is exactly the durable copy this posture denies having."""
    body = (TERRAFORM / "analysis_bundle.tf").read_text(encoding="utf-8")
    versioning = re.search(r"versioning\s*\{\s*enabled\s*=\s*(\w+)", body)
    assert versioning and versioning.group(1) == "false", (
        "object versioning must be off: a noncurrent version survives the delete rule the "
        "console's promise depends on"
    )


def test_the_bucket_is_regional_and_encrypted_with_the_regional_key() -> None:
    body = (TERRAFORM / "analysis_bundle.tf").read_text(encoding="utf-8")
    assert "location = var.region" in body, (
        "borrower evidence must sit in the deploy region, not a multi-region"
    )
    assert "google_kms_crypto_key.credit_memo.id" in body, "CMEK is not applied to the bucket"
    assert 'public_access_prevention    = "enforced"' in body.replace("  ", "  ")


@pytest.mark.parametrize("days", [0, -1, 91, 3650])
def test_a_window_terraform_would_refuse_fails_at_load(days: int) -> None:
    """Both halves validate the same range, so a bad number cannot reach only one of them."""
    with pytest.raises(ValueError, match="between 1 and 90"):
        Settings(analysis_bundle=AnalysisBundleSettings(retention_days=days))


@pytest.mark.parametrize("days", [1, 15, 90])
def test_a_window_terraform_would_accept_loads(days: int) -> None:
    assert (
        Settings(
            analysis_bundle=AnalysisBundleSettings(retention_days=days)
        ).analysis_bundle.retention_days
        == days
    )


def test_terraform_validates_the_same_range_the_application_does() -> None:
    body = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
    block = re.search(r'variable "analysis_retention_days" \{(.*?)\n\}', body, re.S)
    assert block
    assert "var.analysis_retention_days >= 1" in block.group(1)
    assert "var.analysis_retention_days <= 90" in block.group(1)


# --------------------------------------------------------------------------- #
# What the posture retired, and must stay retired
# --------------------------------------------------------------------------- #
def test_no_locked_worm_bucket_outlives_the_evidence_it_describes() -> None:
    """A seven-year locked log about analyses deleted in fifteen days is not a trail.

    It is a record that outlives its own subject by a factor of a hundred and seventy,
    taken irreversibly on an operator's behalf. An adopter running this as a system of
    record restores it AND raises the retention window — in that order, because a locked
    bucket cannot be undone if the second half turns out to be wrong.
    """
    for path in TERRAFORM.glob("*.tf"):
        assert "locked = true" not in _code(path), (
            f"{path.name} locks a retention bucket irreversibly"
        )


def test_no_standing_index_or_processor_is_provisioned() -> None:
    """Agent Search serves no Cloud region, and the processor routed bytes off-region.

    Both are gone, and retrieval and extraction happen in-process instead. A future change
    that reintroduces either has to delete this test, which is the point.
    """
    provisioned = "\n".join(_code(path) for path in TERRAFORM.glob("*.tf"))
    for resource in ("google_document_ai_processor", "google_discovery_engine"):
        assert resource not in provisioned, f"{resource} is provisioned again"
