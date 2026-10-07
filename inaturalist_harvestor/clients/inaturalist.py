"""iNaturalist API client: authentication and observation harvesting."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Iterator

from ..config import InaturalistSettings
from ..http import HttpClient
from ..models import Observation

logger = logging.getLogger(__name__)

# The v2 API silently caps per_page at 200 records regardless of
# what is requested, so the effective page size must be clamped.
MAX_PER_PAGE = 200

# The projection of observation fields we request from the API.
OBSERVATION_FIELDS = (
    "("
    "id:!t,observed_on:!t,created_at:!t,species_guess:!t,"
    "taxon:(id:!t,name:!t,rank:!t),"
    "user:(id:!t,login:!t),"
    "latitude:!t,longitude:!t,positional_accuracy:!t,quality_grade:!t,"
    "geojson:(point:!t),private_geojson:(point:!t),"
    "location:!t,private_location:!t"
    ")"
)


class InaturalistAuthenticationError(RuntimeError):
    """Raised when authentication against iNaturalist fails."""


class InaturalistAuthenticator:
    """Obtains the short-lived JWT used by the v2 API.

    The v2 API requires a JWT obtained via a two-step flow:
    first an OAuth token from the OAuth password grant, then
    exchanged for the actual API token.
    """

    def __init__(
        self, http: HttpClient, settings: InaturalistSettings
    ) -> None:
        self._http = http
        self._settings = settings

    def obtain_api_token(self) -> str:
        oauth_token = self._obtain_oauth_token()
        return self._exchange_for_jwt(oauth_token)

    def _obtain_oauth_token(self) -> str:
        logger.info("Obtaining OAuth token...")

        data = self._http.post(
            f"{self._settings.site_url}/oauth/token",
            data={
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "grant_type": "password",
                "username": self._settings.username,
                "password": self._settings.password,
            },
        )

        if "access_token" not in data:
            raise InaturalistAuthenticationError(
                f"No access_token in OAuth response: {data}"
            )

        return data["access_token"]

    def _exchange_for_jwt(self, oauth_token: str) -> str:
        logger.info("Obtaining JWT...")

        data = self._http.get(
            f"{self._settings.site_url}/users/api_token",
            headers={"Authorization": f"Bearer {oauth_token}"},
        )

        if "api_token" not in data:
            raise InaturalistAuthenticationError(
                f"No api_token in response: {data}"
            )

        return data["api_token"]


class InaturalistClient:
    """Reads project observations from the iNaturalist v2 API."""

    def __init__(
        self,
        http: HttpClient,
        settings: InaturalistSettings,
        request_delay: float,
        api_token: str,
    ) -> None:
        self._http = http
        self._settings = settings
        self._request_delay = request_delay
        self._api_token = api_token

    def iter_observation_batches(
        self, created_after: datetime | None = None
    ) -> Iterator[list[Observation]]:
        """Yield observations in batches.

        The v2 API caps per_page at 200 records regardless of what
        we request, so the effective page size is clamped and also
        used for the last-page check. iNaturalist limits normal
        pagination to 10,000 records, therefore we page with an
        id_above cursor ordered by id; created_after is used for
        the daily incremental import.
        """
        page_size = min(self._settings.per_page, MAX_PER_PAGE)
        last_id = 0
        imported = 0

        while True:
            params = {
                "project_id": self._settings.project_id,
                "per_page": page_size,
                "id_above": last_id,
                "order_by": "id",
                "order": "asc",
                "fields": OBSERVATION_FIELDS,
            }

            if created_after is not None:
                params["created_d1"] = created_after.strftime("%Y-%m-%d")

            payload = self._http.get(
                f"{self._settings.api_url}/observations",
                params=params,
                headers={"Authorization": f"Bearer {self._api_token}"},
                timeout=120,
            )

            total = payload.get("total_results")  # type: ignore[union-attr]
            results = payload.get("results", [])  # type: ignore[union-attr]

            if not results:
                break

            yield [Observation.from_api(item) for item in results]

            imported += len(results)
            page_last_id = results[-1]["id"]

            logger.info(
                "Imported %s / %s — last id %s",
                imported,
                total if total is not None else "?",
                page_last_id,
            )

            if page_last_id <= last_id:
                raise RuntimeError(
                    "iNaturalist pagination did not advance "
                    f"(cursor stuck at {last_id}); aborting."
                )

            last_id = page_last_id

            if len(results) < page_size:
                break

            # Do not hammer external APIs.
            time.sleep(self._request_delay)
