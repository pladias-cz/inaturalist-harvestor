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

        harvested = self._harvest()

        if not self._removal_is_safe(sync_started_at, harvested):
            return

        removed = self._observations.mark_missing_as_removed(
            sync_started_at
        )

        logger.info(
            "Marked %d observations as no longer in project.", removed
        )

    def _removal_is_safe(
        self, sync_started_at: datetime, harvested: int
    ) -> bool:
        """Decide whether observations may be flagged as removed.

        The removal pass trusts that the harvest enumerated the whole
        project, so it is skipped when the harvest looks incomplete:
        either nothing was harvested at all, or the pass would flag
        more than the configured share of the table while the run saw
        fewer observations than that.
        """
        if harvested == 0:
            logger.warning(
                "Harvest returned no observations, "
                "skipping the removal pass."
            )
            return False

        total = self._observations.count_records()
        candidates = self._observations.count_not_seen_since(
            sync_started_at
        )
        ratio = candidates / total if total else 0.0
        limit = self._settings.max_removal_ratio

        # A share above the limit is suspicious only while the pass
        # would flag more observations than the harvest enumerated: a
        # healthy run sees far more records than the project has just
        # lost, while an early stop flags almost all of them.
        if ratio > limit and candidates > harvested:
            logger.warning(
                "Skipping the removal pass: it would flag %d of %d "
                "observations (%.1f %%) as removed which exceeds both "
                "the limit of %.1f %% and the %d observations "
                "harvested by this run.",
                candidates,
                total,
                ratio * 100,
                limit * 100,
                harvested,
            )
            return False

        return True

    def _harvest(
        self, created_after: datetime | None = None
    ) -> int:
        """Store the harvested observations, return their count."""
        harvested = 0

        for batch in self._client.iter_observation_batches(
            created_after=created_after
        ):
            self._save_batch(batch)
            harvested += len(batch)

        logger.info("Harvested %d observations.", harvested)
        return harvested

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
