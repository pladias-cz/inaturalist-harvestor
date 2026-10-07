"""Orchestrates the harvest of iNaturalist project observations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from ..clients.inaturalist import InaturalistClient
from ..config import Settings
from ..db.connection import Database
from ..db.observations import ObservationRepository
from ..db.taxa import TaxonRepository
from ..models import Observation

logger = logging.getLogger(__name__)


class ObservationImportService:
    """Imports project observations, full or incremental."""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        client: InaturalistClient,
        taxa: TaxonRepository,
        observations: ObservationRepository,
    ) -> None:
        self._settings = settings
        self._database = database
        self._client = client
        self._taxa = taxa
        self._observations = observations

    def run_daily(self) -> None:
        """Incremental import of recently created observations.

        Deliberately overlaps the previous period (see
        Settings.daily_overlap) which makes the import robust
        against timestamps and interrupted runs.
        """
        last_created_at = self._observations.find_last_created_at()

        if last_created_at is None:
            logger.info("No existing data. Running full import.")
            self.run_full()
            return

        created_after = last_created_at - self._settings.daily_overlap

        logger.info("Daily import from %s", created_after.isoformat())

        self._harvest(created_after=created_after)

    def run_full(self) -> None:
        """Full synchronization of all project observations."""
        sync_started_at = datetime.now(timezone.utc)

        logger.info(
            "Starting full synchronization at %s",
            sync_started_at.isoformat(),
        )

        self._harvest()

        removed = self._observations.mark_missing_as_removed(
            sync_started_at
        )

        logger.info(
            "Marked %d observations as no longer in project.", removed
        )

    def _harvest(self, created_after=None) -> None:
        for batch in self._client.iter_observation_batches(
            created_after=created_after
        ):
            self._save_batch(batch)

    def _save_batch(
        self, observations: Sequence[Observation]
    ) -> None:
        sync_time = datetime.now(timezone.utc)

        # Deduplicate taxa within the batch.
        taxa = {}
        for observation in observations:
            taxon = observation.taxon
            if taxon is not None and taxon.id:
                taxa[taxon.id] = taxon

        # Taxon cache and observations are committed together.
        with self._database.transaction() as conn:
            self._taxa.upsert_batch(conn, list(taxa.values()))
            self._observations.upsert_batch(
                conn, observations, sync_time
            )
