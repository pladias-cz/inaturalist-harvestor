"""Tests for the shared HTTP client."""

import unittest
from unittest import mock

import requests

from inaturalist_harvestor.http import HttpClient


def _response(status_code=200, payload=None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    return response


class HttpClientTest(unittest.TestCase):

    def _client(self):
        client = HttpClient("test-agent", rate_limit_wait=0)
        return client

    def test_get_returns_json(self):
        client = self._client()

        with mock.patch.object(
            client._session,
            "request",
            return_value=_response(payload={"result": 1}),
        ) as request:
            data = client.get("https://example.test/api")

        self.assertEqual(data, {"result": 1})
        request.assert_called_once()
        _, kwargs = request.call_args
        self.assertEqual(kwargs["timeout"], 60)

    def test_rate_limit_is_retried(self):
        client = self._client()

        responses = [
            _response(status_code=429),
            _response(payload={"ok": True}),
        ]

        with mock.patch.object(
            client._session, "request", side_effect=responses
        ) as request:
            data = client.get("https://example.test/api")

        self.assertEqual(data, {"ok": True})
        self.assertEqual(request.call_count, 2)

    def test_error_status_raises(self):
        client = self._client()

        response = _response(status_code=500)
        response.raise_for_status.side_effect = requests.HTTPError(
            "500"
        )

        with mock.patch.object(
            client._session, "request", return_value=response
        ):
            with self.assertRaises(requests.HTTPError):
                client.get("https://example.test/api")


if __name__ == "__main__":
    unittest.main()
