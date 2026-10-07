"""Orchestrates GBIF resolution of pending taxa."""

from __future__ import annotations

import logging
import time

from ..clients.gbif import GbifClient
from ..config import Settings
from ..db.taxa import TaxonRepository

logger = logging.getLogger(__name__)


class TaxonResolutionService:
    """Resolves all pending taxa using GBIF Species Match."""

    def __init__(
        self,
        settings: Settings,
        gbif: GbifClient,
        taxa: TaxonRepository,
    ) -> None:
        self._settings = settings
        self._gbif = gbif
        self._taxa = taxa

    def run(self) -> None:
        pending = self._taxa.find_pending()

        logger.info("%d pending taxon(s) to resolve.", len(pending))

        for index, taxon in enumerate(pending, start=1):
            logger.info(
                "Resolving %d/%d: %s %s (%s)",
                index,
                len(pending),
                taxon.id,
                taxon.name,
                taxon.rank,
            )

            try:
                match = self._gbif.match_species(taxon.name, taxon.rank)
                self._taxa.save_resolution(taxon.id, match)
            except Exception:
                logger.exception(
                    "Failed to resolve taxon %s %s",
                    taxon.id,
                    taxon.name,
                )

            time.sleep(self._settings.gbif.request_delay)
