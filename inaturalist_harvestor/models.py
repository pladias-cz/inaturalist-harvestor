"""Domain models and parsing of raw API payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp as returned by iNaturalist."""
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_location(
    value: str | None,
) -> tuple[float | None, float | None]:
    """Parse an iNaturalist "latitude,longitude" location string."""
    if not value:
        return None, None

    try:
        latitude, longitude = value.split(",")
        return float(latitude), float(longitude)
    except (ValueError, AttributeError):
        return None, None


@dataclass(frozen=True)
class Taxon:
    """An iNaturalist taxon as referenced by an observation."""

    id: int
    name: str | None
    rank: str | None
    data: Mapping[str, Any]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Taxon":
        return cls(
            id=payload["id"],
            name=payload.get("name"),
            rank=payload.get("rank"),
            data=payload,
        )


@dataclass(frozen=True)
class User:
    """The iNaturalist user who created an observation."""

    id: int | None
    login: str | None


@dataclass(frozen=True)
class Observation:
    """An iNaturalist observation."""

    id: int
    created_at: datetime | None
    updated_at: datetime | None
    observed_on: str | None
    taxon: Taxon | None
    user: User
    latitude: float | None
    longitude: float | None
    positional_accuracy: float | None
    quality_grade: str | None
    species_guess: str | None
    data: Mapping[str, Any]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "Observation":
        taxon_payload = payload.get("taxon") or None
        user_payload = payload.get("user") or {}
        latitude, longitude = parse_location(payload.get("location"))

        return cls(
            id=payload["id"],
            created_at=parse_datetime(payload.get("created_at")),
            updated_at=parse_datetime(payload.get("updated_at")),
            observed_on=payload.get("observed_on"),
            taxon=(
                Taxon.from_api(taxon_payload)
                if taxon_payload else None
            ),
            user=User(
                id=user_payload.get("id"),
                login=user_payload.get("login"),
            ),
            latitude=latitude,
            longitude=longitude,
            positional_accuracy=payload.get("positional_accuracy"),
            quality_grade=payload.get("quality_grade"),
            species_guess=payload.get("species_guess"),
            data=payload,
        )


@dataclass(frozen=True)
class GbifMatch:
    """Result of a GBIF Species Match request."""

    usage_key: int | None
    accepted_usage_key: int | None
    scientific_name: str | None
    rank: str | None
    match_type: str | None
    confidence: float | None
    data: Mapping[str, Any]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "GbifMatch":
        return cls(
            usage_key=payload.get("usageKey"),
            accepted_usage_key=payload.get("acceptedUsageKey"),
            scientific_name=payload.get("scientificName"),
            rank=payload.get("rank"),
            match_type=payload.get("matchType"),
            confidence=payload.get("confidence"),
            data=payload,
        )

    @property
    def status(self) -> str:
        """Resolution status derived from the match.

        We consider an exact / fuzzy / higher-rank GBIF match as
        "matched". No-match stays explicitly "unmatched".
        """
        if self.usage_key is not None:
            return "matched"
        return "unmatched"
