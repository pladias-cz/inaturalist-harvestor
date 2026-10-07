"""Tests for the ChecklistBank client."""

import unittest
from typing import Any, Mapping

import requests

from inaturalist_harvestor.clients.checklistbank import (
    ChecklistbankClient,
)
from inaturalist_harvestor.config import ChecklistbankSettings
from inaturalist_harvestor.http import HttpClient

SETTINGS = ChecklistbankSettings(
    api_url="https://api.checklistbank.org",
    dataset_id=139831,
    dataset_key="3LR",
    request_delay=0.2,
)

ACCEPTED = {
    "id": "L3KM",
    "name": "Battus philenor",
    "authorship": "(Linnaeus, 1771)",
    "rank": "species",
    "status": "accepted",
}


class StubHttpClient(HttpClient):
    """Records requests and replays a canned response."""

    def __init__(
        self,
        payload: Mapping[str, Any] | list[Any] | None = None,
        error: requests.HTTPError | None = None,
    ) -> None:
        super().__init__("stub-http-client")
        self.payload = payload
        self.error = error
        self.requested_url: str | None = None
        self.requested_params = None

    def get(  # type: ignore[override]
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        self.requested_url = url
        self.requested_params = params

        if self.error is not None:
            raise self.error

        if self.payload is None:
            raise AssertionError("No canned response configured")

        return self.payload


class ChecklistbankClientTest(unittest.TestCase):

    def test_resolve_builds_expected_url(self):
        http = StubHttpClient(payload=[ACCEPTED])
        client = ChecklistbankClient(
            http, SETTINGS, "https://www.inaturalist.org"
        )

        resolution = client.resolve(123456)

        self.assertEqual(
            http.requested_url,
            "https://api.checklistbank.org"
            "/dataset/139831"
            "/nameusage"
            "/https%3A%2F%2Fwww.inaturalist.org%2Ftaxa%2F123456"
            "/related",
        )
        self.assertEqual(
            http.requested_params, {"datasetKey": "3LR"}
        )

        self.assertEqual(resolution.col_id, "L3KM")
        self.assertEqual(resolution.status, "matched")

    def test_resolve_strips_trailing_slash_from_site_url(self):
        http = StubHttpClient(payload=[])
        client = ChecklistbankClient(
            http, SETTINGS, "https://www.inaturalist.org/"
        )

        client.resolve(1)

        self.assertIn(
            "https%3A%2F%2Fwww.inaturalist.org%2Ftaxa%2F1",
            http.requested_url or "",
        )

    def test_resolve_404_is_unmatched(self):
        response = requests.Response()
        response.status_code = 404
        http = StubHttpClient(
            error=requests.HTTPError(response=response)
        )
        client = ChecklistbankClient(
            http, SETTINGS, "https://www.inaturalist.org"
        )

        resolution = client.resolve(123456)

        self.assertIsNone(resolution.col_id)
        self.assertEqual(resolution.status, "unmatched")

    def test_resolve_other_http_errors_propagate(self):
        response = requests.Response()
        response.status_code = 500
        http = StubHttpClient(
            error=requests.HTTPError(response=response)
        )
        client = ChecklistbankClient(
            http, SETTINGS, "https://www.inaturalist.org"
        )

        with self.assertRaises(requests.HTTPError):
            client.resolve(123456)


if __name__ == "__main__":
    unittest.main()
