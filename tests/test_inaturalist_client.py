"""Tests for iNaturalist observation pagination."""

import unittest
from datetime import datetime, timezone
from typing import Any, Mapping

from inaturalist_harvestor.clients.inaturalist import (
    MAX_PER_PAGE,
    InaturalistClient,
)
from inaturalist_harvestor.config import InaturalistSettings
from inaturalist_harvestor.http import HttpClient


def make_settings(per_page: int) -> InaturalistSettings:
    return InaturalistSettings(
        site_url="https://www.inaturalist.org",
        api_url="https://api.inaturalist.org/v2",
        project_id=183334,
        per_page=per_page,
        username="user",
        password="password",
        client_id="client-id",
        client_secret="client-secret",
    )


def page(ids: list[int], total: int) -> dict:
    return {
        "total_results": total,
        "results": [
            {"id": id_, "created_at": "2024-05-01T12:00:00Z"}
            for id_ in ids
        ],
    }


class StubHttpClient(HttpClient):
    """Records requests and replays canned page payloads."""

    def __init__(self, pages: list[Mapping[str, Any]]) -> None:
        super().__init__("stub-http-client")
        self._pages = list(pages)
        self.requests: list[dict] = []

    def get(  # type: ignore[override]
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        self.requests.append(
            {"url": url, "params": dict(params or {})}
        )

        if self._pages:
            return self._pages.pop(0)

        return {"total_results": 0, "results": []}


class IterObservationBatchesTest(unittest.TestCase):

    def make_client(
        self, pages: list[Mapping[str, Any]], per_page: int = 1000
    ) -> tuple[InaturalistClient, StubHttpClient]:
        http = StubHttpClient(pages)
        client = InaturalistClient(
            http,
            make_settings(per_page),
            request_delay=0,
            api_token="token",
        )
        return client, http

    def test_paginates_beyond_api_per_page_cap(self):
        # per_page=1000 is requested but the API caps pages at 200
        # records; the client must keep paginating nevertheless.
        client, http = self.make_client(
            [
                page(list(range(1, 201)), 405),
                page(list(range(201, 401)), 405),
                page(list(range(401, 406)), 405),
            ]
        )

        batches = list(client.iter_observation_batches())

        self.assertEqual(
            [len(batch) for batch in batches], [200, 200, 5]
        )
        self.assertEqual(len(http.requests), 3)

        # Every page is requested with the capped page size and an
        # advancing id_above cursor.
        self.assertEqual(
            [request["params"]["per_page"] for request in http.requests],
            [MAX_PER_PAGE] * 3,
        )
        self.assertEqual(
            [request["params"]["id_above"] for request in http.requests],
            [0, 200, 400],
        )
        for request in http.requests:
            self.assertEqual(request["params"]["order_by"], "id")
            self.assertEqual(request["params"]["order"], "asc")

    def test_stops_on_empty_page(self):
        client, http = self.make_client(
            [
                page(list(range(1, 201)), 200),
                page([], 0),
            ]
        )

        batches = list(client.iter_observation_batches())

        self.assertEqual([len(batch) for batch in batches], [200])
        self.assertEqual(len(http.requests), 2)

    def test_created_after_is_sent_as_date_filter(self):
        client, http = self.make_client([page([], 0)])

        created_after = datetime(
            2024, 5, 1, 12, 0, 0, tzinfo=timezone.utc
        )
        list(client.iter_observation_batches(created_after))

        self.assertEqual(
            http.requests[0]["params"]["created_d1"], "2024-05-01"
        )

    def test_stuck_cursor_raises(self):
        # Pages fill the requested page size (2) so the loop keeps
        # paginating; the second page fails to advance the cursor.
        client, http = self.make_client(
            [
                page([10, 20], 4),
                page([15, 20], 4),  # cursor does not advance
            ],
            per_page=2,
        )

        with self.assertRaises(RuntimeError):
            list(client.iter_observation_batches())


if __name__ == "__main__":
    unittest.main()
