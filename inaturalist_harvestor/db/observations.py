"""Repository for harvested iNaturalist observations."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import psycopg
from psycopg.types.json import Jsonb

from ..models import Observation
from .connection import Database
from .schema import RECORDS_TABLE

# Every observation returned by the project feed counts as a sighting,
# so the conflict update must never be conditional. A WHERE-gated update
# leaves the whole row untouched (including last_seen_in_project), which
# makes the removal pass flag observations that are still in the project.
_UPSERT_SQL = f"""
    INSERT INTO {RECORDS_TABLE} (
        id,
        created_at,
        updated_at,
        observed_on,
        taxon_id,
        taxon_name,
        taxon_rank,
        user_id,
        user_login,
        latitude,
        longitude,
        geom,
        positional_accuracy,
        quality_grade,
        species_guess,
        location_visibility,
        in_project,
        last_seen_in_project,
        data,
        imported_at
    )
    VALUES (
        %(id)s,
        %(created_at)s,
        %(updated_at)s,
        %(observed_on)s,
        %(taxon_id)s,
        %(taxon_name)s,
        %(taxon_rank)s,
        %(user_id)s,
        %(user_login)s,
        %(latitude)s,
        %(longitude)s,
        ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326),
        %(positional_accuracy)s,
        %(quality_grade)s,
        %(species_guess)s,
        %(location_visibility)s,
        true,
        %(last_seen_in_project)s,
        %(data)s,
        now()
    )
    ON CONFLICT (id) DO UPDATE SET
        created_at = EXCLUDED.created_at,
        updated_at = EXCLUDED.updated_at,
        observed_on = EXCLUDED.observed_on,
        taxon_id = EXCLUDED.taxon_id,
        taxon_name = EXCLUDED.taxon_name,
        taxon_rank = EXCLUDED.taxon_rank,
        user_id = EXCLUDED.user_id,
        user_login = EXCLUDED.user_login,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        geom = EXCLUDED.geom,
        positional_accuracy = EXCLUDED.positional_accuracy,
        quality_grade = EXCLUDED.quality_grade,
        species_guess = EXCLUDED.species_guess,
        location_visibility = EXCLUDED.location_visibility,
        in_project = true,
        last_seen_in_project = EXCLUDED.last_seen_in_project,
        data = EXCLUDED.data,
        imported_at = now()
"""

# An observation which was not seen by the current full synchronization
# is no longer in the project. The predicate is shared by the count and
# the update so the removal pass can be checked before it is applied.
_MISSING_SINCE_CONDITION = """
    in_project = true
    AND (
        last_seen_in_project IS NULL
        OR last_seen_in_project < %s
    )
"""

_COUNT_MISSING_SQL = f"""
    SELECT count(*)
    FROM {RECORDS_TABLE}
    WHERE {_MISSING_SINCE_CONDITION}
"""

_MARK_MISSING_SQL = f"""
    UPDATE {RECORDS_TABLE}
    SET in_project = false
    WHERE {_MISSING_SINCE_CONDITION}
"""


class ObservationRepository:
    """Persists observations into the records table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def find_last_created_at(self) -> datetime | None:
        """Return the newest observation creation timestamp, if any."""
        with self._database.connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT max(created_at) FROM {RECORDS_TABLE}")
            return cur.fetchone()[0]

    def count_records(self) -> int:
        """Return the number of stored observations."""
        with self._database.connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {RECORDS_TABLE}")
            return cur.fetchone()[0]

    def count_not_seen_since(
        self, sync_started_at: datetime
    ) -> int:
        """Return how many rows the removal pass would flag.

        Used as a sanity check before the removal pass mutates the
        table, so an incomplete harvest cannot silently mark a large
        part of the project as removed.
        """
        with self._database.connect() as conn, conn.cursor() as cur:
            cur.execute(_COUNT_MISSING_SQL, (sync_started_at,))
            return cur.fetchone()[0]

    def upsert_batch(
        self,
        conn: psycopg.Connection,
        observations: Sequence[Observation],
        sync_time: datetime,
    ) -> None:
        """Upsert a batch of observations using the given connection.

        The caller owns the transaction so that the taxon cache and
        the observations can be committed atomically.
        """
        if not observations:
            return

        rows = [
            self._to_row(observation, sync_time)
            for observation in observations
        ]

        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, rows)

    def mark_missing_as_removed(
        self, sync_started_at: datetime
    ) -> int:
        """Mark observations no longer present in the project.

        Any observation which was not encountered during a full
        synchronization is no longer in the project. Returns the
        number of affected rows.
        """
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute(_MARK_MISSING_SQL, (sync_started_at,))
            return cur.rowcount

    @staticmethod
    def _to_row(
        observation: Observation, sync_time: datetime
    ) -> dict:
        taxon = observation.taxon
        user = observation.user

        return {
            "id": observation.id,
            "created_at": observation.created_at,
            "updated_at": observation.updated_at,
            "observed_on": observation.observed_on,
            "taxon_id": taxon.id if taxon else None,
            "taxon_name": taxon.name if taxon else None,
            "taxon_rank": taxon.rank if taxon else None,
            "user_id": user.id,
            "user_login": user.login,
            "latitude": observation.latitude,
            "longitude": observation.longitude,
            "positional_accuracy": observation.positional_accuracy,
            "quality_grade": observation.quality_grade,
            "species_guess": observation.species_guess,
            "location_visibility": observation.location_visibility,
            "last_seen_in_project": sync_time,
            "data": Jsonb(observation.data),
        }
