"""Domain models and parsing of raw API payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence


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
class ColUsage:
    """A ChecklistBank name usage related to an iNaturalist taxon."""

    id: str
    name: str | None
    authorship: str | None
    rank: str | None
    status: str | None
    label: str | None
    data: Mapping[str, Any]

    @classmethod
    def from_api(cls, payload: Mapping[str, Any]) -> "ColUsage":
        return cls(
            id=payload["id"],
            name=payload.get("name"),
            authorship=payload.get("authorship"),
            rank=payload.get("rank"),
            status=payload.get("status"),
            label=payload.get("label"),
            data=payload,
        )


@dataclass(frozen=True)
class ColResolution:
    """Result of resolving an iNaturalist taxon via ChecklistBank.

    Wraps the ``/related`` response of the iNaturalist dataset on
    ChecklistBank and selects the accepted usage, whose id maps to
    the Catalogue of Life (CoL) identifier of the taxon.
    """

    usage: ColUsage | None
    data: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_related_response(
        cls, payload: Sequence[Mapping[str, Any]]
    ) -> "ColResolution":
        """Pick the first accepted usage from the related usages."""

        accepted = next(
            (
                usage
                for usage in payload
                if usage.get("status") == "accepted"
            ),
            None,
        )

        return cls(
            usage=ColUsage.from_api(accepted) if accepted else None,
            data=tuple(payload),
        )

    @property
    def col_id(self) -> str | None:
        """CoL identifier of the resolved usage (e.g. ``L3KM``)."""
        if self.usage is not None:
            return self.usage.id
        return None

    @property
    def col_name(self) -> str | None:
        if self.usage is not None:
            return self.usage.name
        return None

    @property
    def col_rank(self) -> str | None:
        if self.usage is not None:
            return self.usage.rank
        return None

    @property
    def status(self) -> str:
        """Resolution status derived from the related usages.

        An accepted usage means "matched"; anything else (empty
        response, synonyms only, ...) stays explicitly "unmatched".
        """
        if self.usage is not None:
            return "matched"
        return "unmatched"
