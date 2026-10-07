"""Orchestrates ChecklistBank resolution of pending taxa."""

from __future__ import annotations

import logging
import time

from ..clients.checklistbank import ChecklistbankClient
from ..config import Settings
from ..db.taxa import TaxonRepository

logger = logging.getLogger(__name__)


class TaxonResolutionService:
    """Resolves all pending taxa using ChecklistBank."""

    def __init__(
        self,
        settings: Settings,
        checklistbank: ChecklistbankClient,
        taxa: TaxonRepository,
    ) -> None:
        self._settings = settings
        self._checklistbank = checklistbank
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
                resolution = self._checklistbank.resolve(taxon.id)
                self._taxa.save_resolution(taxon.id, resolution)
            except Exception:
                logger.exception(
                    "Failed to resolve taxon %s %s",
                    taxon.id,
                    taxon.name,
                )

            time.sleep(self._settings.checklistbank.request_delay)
