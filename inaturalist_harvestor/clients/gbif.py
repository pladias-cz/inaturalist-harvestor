"""GBIF API client for taxon resolution."""

from __future__ import annotations

from ..config import GbifSettings
from ..http import HttpClient
from ..models import GbifMatch


class GbifClient:
    """Reads GBIF Species Match results."""

    def __init__(self, http: HttpClient, settings: GbifSettings) -> None:
        self._http = http
        self._settings = settings

    def match_species(
        self, name: str, rank: str | None = None
    ) -> GbifMatch:
        """Resolve a scientific name using GBIF Species Match.

        The iNaturalist taxon ID itself is NOT sent as a GBIF key;
        the scientific name is used for matching.
        """
        params = {"name": name}

        if rank:
            params["rank"] = rank

        payload = self._http.get(
            f"{self._settings.api_url}/species/match",
            params=params,
        )

        return GbifMatch.from_api(payload)
