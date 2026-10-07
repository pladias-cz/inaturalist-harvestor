"""Shared HTTP client with rate-limit back-off."""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

import requests

logger = logging.getLogger(__name__)


class HttpClient:
    """Small wrapper around requests.Session.

    Retries requests transparently when the remote API answers
    with HTTP 429 (Too Many Requests), waiting a configurable
    amount of time in between.
    """

    def __init__(
        self,
        user_agent: str,
        timeout: float = 60.0,
        rate_limit_wait: float = 60.0,
    ) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._timeout = timeout
        self._rate_limit_wait = rate_limit_wait

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        return self._request(
            "GET", url, params=params, headers=headers, timeout=timeout
        )

    def post(
        self,
        url: str,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        return self._request(
            "POST", url, data=data, headers=headers, timeout=timeout
        )

    def _request(
        self,
        method: str,
        url: str,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Mapping[str, Any] | list[Any]:
        timeout = timeout if timeout is not None else self._timeout

        while True:
            response = self._session.request(
                method,
                url,
                params=params,
                data=data,
                headers=headers,
                timeout=timeout,
            )

            if response.status_code == 429:
                logger.warning(
                    "Rate limited by %s; sleeping %.0f second(s)...",
                    url,
                    self._rate_limit_wait,
                )
                time.sleep(self._rate_limit_wait)
                continue

            response.raise_for_status()
            return response.json()

    def close(self) -> None:
        self._session.close()
