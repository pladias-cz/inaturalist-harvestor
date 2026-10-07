"""ChecklistBank API client for taxon resolution."""

from __future__ import annotations

from urllib.parse import quote

import requests

from ..config import ChecklistbankSettings
from ..http import HttpClient
from ..models import ColResolution


class ChecklistbankClient:
    """Resolves iNaturalist taxa via ChecklistBank name usages."""

    def __init__(
        self,
        http: HttpClient,
        settings: ChecklistbankSettings,
        inat_site_url: str,
    ) -> None:
        self._http = http
        self._settings = settings
        self._inat_site_url = inat_site_url.rstrip("/")

    def resolve(self, taxon_id: int) -> ColResolution:
        """Resolve an iNaturalist taxon against ChecklistBank.

        The iNaturalist taxon is looked up in the iNaturalist
        dataset on ChecklistBank by its external identifier (the
        iNaturalist taxon URL) and the related usages of the
        target dataset (e.g. the Catalogue of Life) are returned.
        """
        external_id = quote(
            f"{self._inat_site_url}/taxa/{taxon_id}", safe=""
        )
        url = (
            f"{self._settings.api_url}"
            f"/dataset/{self._settings.dataset_id}"
            f"/nameusage/{external_id}/related"
        )

        try:
            payload = self._http.get(
                url,
                params={"datasetKey": self._settings.dataset_key},
            )
        except requests.HTTPError as error:
            # An unknown taxon ID yields 404; treat it as an empty
            # answer so the taxon is marked unmatched instead of
            # staying pending forever.
            response = error.response
            if response is not None and response.status_code == 404:
                return ColResolution.from_related_response([])
            raise

        return ColResolution.from_related_response(payload)
