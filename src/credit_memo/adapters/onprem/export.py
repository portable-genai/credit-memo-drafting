"""On-prem placeholder for ``ExportPort`` — the sovereign target.

A reversibility (P-02, P-12) migration placeholder. Most banks render committee packs
through their own template service, and this is where it binds.

The contract to keep, because an exporter is exactly where it gets dropped: the pack
carries the input manifest, the provenance label on every figure, and the standing
"decision support, not a credit decision" sentence — and it carries no web-grounded
content, which may only be shown to the person who ran the query.
``domain/memo_document.build_document`` supplies all of that already; an implementation
should render its blocks rather than re-deciding what a pack says.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import CreditMemo

_MESSAGE = (
    "On-prem ExportPort adapter is a migration placeholder; render "
    "domain/memo_document.build_document() through your own template service rather than "
    "re-deciding what a committee pack contains. Core domain logic is unchanged."
)


class OnPremExportAdapter:
    """Placeholder export adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def formats(self) -> tuple[str, ...]:
        return ()

    def export(self, memo: CreditMemo, fmt: str = "docx") -> tuple[bytes, str]:
        raise NotImplementedError(_MESSAGE)
