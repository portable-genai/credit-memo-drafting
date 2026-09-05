"""ExportPort — the committee pack, in a format that can leave the application.

A memo that exists only inside a web console has not reached the people who decide. A
committee reads a document, an examiner asks for one years later, and both expect it to
carry its own provenance rather than a link back to a system they cannot log into.

Two properties every implementation must keep, because the memo's credibility rests on
them and an exporter is exactly where they get quietly dropped:

* **The manifest and the provenance legend travel with it.** A reader holding the exported
  pack must be able to see which files it was assessed on, when that evidence expires, and
  which figures were computed rather than drafted. Those are the parts that make the
  numbers checkable, and they are the first things a "clean" export tends to lose.
* **Web-grounded content never appears.** Grounded search results may be shown only to the
  person who ran the query (Google's Service Specific Terms section 20(k)), and an export
  is by definition read by other people. The research panel is analyst-only and ephemeral;
  an exporter that included it would breach the terms silently, so
  ``tests/unit/test_export_contract.py`` asserts its absence rather than trusting it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import CreditMemo


@runtime_checkable
class ExportPort(Protocol):
    def export(self, memo: CreditMemo, fmt: str = "docx") -> tuple[bytes, str]:
        """Render ``memo`` and return its bytes and content type.

        ``fmt`` is "docx", "pdf" or "html". An implementation that cannot produce a format
        raises rather than silently substituting another: a caller who asked for a Word
        document and received HTML will find out at the worst moment.
        """
        ...

    def formats(self) -> tuple[str, ...]:
        """Which formats this deployment can actually produce."""
        ...
