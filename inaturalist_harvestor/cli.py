"""Command line entry point wiring all components together."""

from __future__ import annotations

import logging
import sys

from .clients.gbif import GbifClient
from .clients.inaturalist import (
    InaturalistAuthenticator,
    InaturalistClient,
)
from .config import Settings
from .db.connection import Database
from .db.observations import ObservationRepository
from .db.taxa import TaxonRepository
from .http import HttpClient
from .services.import_service import ObservationImportService
from .services.taxon_resolution import TaxonResolutionService

logger = logging.getLogger(__name__)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    """Run one import cycle (observations + taxon resolution)."""
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    logger.info(
        "Starting iNaturalist import: %s", settings.import_mode
    )

    http = HttpClient(settings.user_agent)
    database = Database(settings.database.url)
    taxa = TaxonRepository(database)
    observations = ObservationRepository(database)

    api_token = InaturalistAuthenticator(
        http, settings.inaturalist
    ).obtain_api_token()

    import_service = ObservationImportService(
        settings=settings,
        database=database,
        client=InaturalistClient(
            http,
            settings.inaturalist,
            request_delay=settings.request_delay,
            api_token=api_token,
        ),
        taxa=taxa,
        observations=observations,
    )

    if settings.import_mode == "daily":
        import_service.run_daily()
    else:
        import_service.run_full()

    resolution_service = TaxonResolutionService(
        settings=settings,
        gbif=GbifClient(http, settings.gbif),
        taxa=taxa,
    )
    resolution_service.run()

    logger.info("Import finished.")


if __name__ == "__main__":
    main()
