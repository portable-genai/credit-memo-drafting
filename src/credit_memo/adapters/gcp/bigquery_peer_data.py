"""BigQuery peer-data adapter (PeerDataPort).

Primary production peer-financials backend for B2: a curated peer dataset in **BigQuery**
in ``asia-southeast1`` (Singapore), CMEK-encrypted. For a borrower's metric it queries
the peer cohort (same sector) and returns one :class:`PeerMetric` per peer; the domain
service computes the median and the borrower's percentile arithmetically, so peer numbers
are never invented.

This is internal data, so there is no ``platform`` HTTP adapter. The ``google-cloud-
bigquery`` import is lazy so on-prem and test profiles import this module with no GCP SDK
installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import Borrower, PeerMetric

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.cloud import bigquery


class BigQueryPeerDataAdapter:
    """Look up peer financials from a CMEK-encrypted BigQuery dataset."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cfg = settings.peer_data
        self._client: Any | None = None

    def _get_client(self) -> bigquery.Client:
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(
                project=self._settings.project_id, location=self._cfg.location
            )
        return self._client

    def peers_for(self, borrower: Borrower, metric: str) -> list[PeerMetric]:
        """Return the peer cohort's values for ``metric`` (same sector)."""
        from google.cloud import bigquery

        client = self._get_client()
        table = f"{self._settings.project_id}.{self._cfg.dataset}.{self._cfg.table}"
        query = (
            f"SELECT peer_name, metric, value FROM `{table}` "
            "WHERE sector = @sector AND metric = @metric "
            "ORDER BY value ASC LIMIT @max_peers"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sector", "STRING", borrower.sector),
                bigquery.ScalarQueryParameter("metric", "STRING", metric),
                bigquery.ScalarQueryParameter("max_peers", "INT64", self._cfg.max_peers),
            ]
        )
        rows = client.query(query, job_config=job_config).result()
        return [
            PeerMetric(
                peer_name=str(row["peer_name"]),
                metric=str(row["metric"]),
                value=float(row["value"]),
            )
            for row in rows
        ]
