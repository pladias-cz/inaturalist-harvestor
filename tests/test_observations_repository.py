"""Integration tests for observation persistence.

They need a PostgreSQL with PostGIS which is safe to wipe, because the
``gbif`` schema of the target database is recreated from
``structure.sql`` before the tests run:

    TEST_DATABASE_URL=postgresql://user:password@localhost:7788/test \\
        python -m unittest discover -s tests -v
"""

import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from inaturalist_harvestor.db.schema import RECORDS_TABLE, TAXA_TABLE
from inaturalist_harvestor.models import Observation, Taxon, User

try:
    import psycopg

    from inaturalist_harvestor.db.connection import Database
    from inaturalist_harvestor.db.observations import (
        ObservationRepository,
    )
    from inaturalist_harvestor.db.taxa import TaxonRepository
except ImportError as error:
    # Nothing else of the test module is usable without them.
    MISSING_DEPENDENCY = str(error)
else:
    MISSING_DEPENDENCY = None

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
STRUCTURE_SQL = (
    Path(__file__).resolve().parent.parent / "structure.sql"
)

TAXON = Taxon(id=1, name="Ophrys apifera", rank="species", data={})


def make_observation(
    id_: int, quality_grade: str = "research"
) -> Observation:
    return Observation(
        id=id_,
        created_at=datetime(2024, 5, 1, 12, tzinfo=timezone.utc),
        updated_at=datetime(2024, 5, 2, 12, tzinfo=timezone.utc),
        observed_on="2024-04-30",
        taxon=TAXON,
        user=User(id=42, login="naturalist"),
        latitude=50.1,
        longitude=14.5,
        positional_accuracy=20,
        quality_grade=quality_grade,
        species_guess="Bee orchid",
        data={"id": id_, "quality_grade": quality_grade},
    )


def schema_sql() -> str:
    """The production schema without its ownership transfers."""
    sql = STRUCTURE_SQL.read_text()
    return re.sub(r"ALTER TABLE[^;]*;", "", sql, flags=re.I | re.S)


@unittest.skipIf(
    MISSING_DEPENDENCY is not None,
    MISSING_DEPENDENCY or "missing dependency",
)
@unittest.skipUnless(
    TEST_DATABASE_URL, "TEST_DATABASE_URL is not set"
)
class ObservationRepositoryTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        # The schema of the scratch database is rebuilt from scratch so
        # that structure.sql (the single source of the shape) is used.
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            conn.execute("DROP SCHEMA IF EXISTS gbif CASCADE")
            conn.execute("CREATE SCHEMA gbif")
            conn.execute(schema_sql())
            conn.commit()

    def setUp(self) -> None:
        self.database = Database(TEST_DATABASE_URL)
        self.observations = ObservationRepository(self.database)
        self.taxa = TaxonRepository(self.database)

        with self.database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"TRUNCATE {RECORDS_TABLE}, {TAXA_TABLE}"
                )

    def save_batch(
        self,
        observations: Sequence[Observation],
        sync_time: datetime,
    ) -> None:
        """Mirror the service: taxa and records commit together."""
        taxa = {o.taxon.id: o.taxon for o in observations if o.taxon}

        with self.database.transaction() as conn:
            self.taxa.upsert_batch(conn, list(taxa.values()))
            self.observations.upsert_batch(
                conn, list(observations), sync_time
            )

    def fetch_row(self, id_: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT in_project,
                           last_seen_in_project,
                           updated_at,
                           quality_grade
                    FROM {RECORDS_TABLE}
                    WHERE id = %s
                    """,
                    (id_,),
                )
                row = cur.fetchone()

        self.assertIsNotNone(row, f"observation {id_} is missing")
        return dict(
            zip(
                (
                    "in_project",
                    "last_seen_in_project",
                    "updated_at",
                    "quality_grade",
                ),
                row,
            )
        )

    def test_unchanged_observation_still_counts_as_a_sighting(self):
        # Regression test: the conflict update used to be gated on the
        # payload having changed, which left last_seen_in_project at
        # its previous value and made the removal pass flag
        # observations which are still in the project.
        first_sync = datetime.now(timezone.utc) - timedelta(hours=2)
        second_sync = datetime.now(timezone.utc) - timedelta(hours=1)

        self.save_batch([make_observation(1)], first_sync)
        self.save_batch([make_observation(1)], second_sync)

        row = self.fetch_row(1)
        self.assertTrue(row["in_project"])
        self.assertEqual(row["last_seen_in_project"], second_sync)
        # updated_at is part of the API projection now, so the payload
        # comparison has something to compare against.
        self.assertEqual(
            row["updated_at"],
            datetime(2024, 5, 2, 12, tzinfo=timezone.utc),
        )

    def test_changed_payload_is_stored(self):
        first_sync = datetime.now(timezone.utc) - timedelta(hours=2)
        second_sync = datetime.now(timezone.utc) - timedelta(hours=1)

        self.save_batch([make_observation(1, "research")], first_sync)
        self.save_batch([make_observation(1, "casual")], second_sync)

        self.assertEqual(
            self.fetch_row(1)["quality_grade"], "casual"
        )

    def test_removal_pass_keeps_observed_and_flags_absent(self):
        old_sync = datetime.now(timezone.utc) - timedelta(hours=2)
        new_sync = datetime.now(timezone.utc) - timedelta(hours=1)

        self.save_batch(
            [make_observation(1), make_observation(2)], old_sync
        )
        # Only the first observation is still in the project.
        self.save_batch([make_observation(1)], new_sync)

        self.assertEqual(self.observations.count_records(), 2)
        self.assertEqual(
            self.observations.count_not_seen_since(new_sync), 1
        )
        self.assertEqual(
            self.observations.mark_missing_as_removed(new_sync), 1
        )

        self.assertTrue(self.fetch_row(1)["in_project"])
        self.assertFalse(self.fetch_row(2)["in_project"])

        # The pass is idempotent.
        self.assertEqual(
            self.observations.count_not_seen_since(new_sync), 0
        )
        self.assertEqual(
            self.observations.mark_missing_as_removed(new_sync), 0
        )

    def test_removal_pass_flags_observation_without_sighting(self):
        with self.database.transaction() as conn:
            self.taxa.upsert_batch(conn, [TAXON])
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {RECORDS_TABLE} (id, data, in_project)
                    VALUES (99, '{{}}'::jsonb, true)
                    """
                )

        sync_started_at = datetime.now(timezone.utc)

        self.assertEqual(
            self.observations.count_not_seen_since(sync_started_at), 1
        )
        self.assertEqual(
            self.observations.mark_missing_as_removed(sync_started_at), 1
        )
        self.assertFalse(self.fetch_row(99)["in_project"])

    def test_returning_observation_is_back_in_the_project(self):
        old_sync = datetime.now(timezone.utc) - timedelta(hours=2)
        removed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        new_sync = datetime.now(timezone.utc)

        self.save_batch([make_observation(1)], old_sync)
        self.observations.mark_missing_as_removed(removed_at)
        self.assertFalse(self.fetch_row(1)["in_project"])

        self.save_batch([make_observation(1)], new_sync)

        row = self.fetch_row(1)
        self.assertTrue(row["in_project"])
        self.assertEqual(row["last_seen_in_project"], new_sync)


if __name__ == "__main__":
    unittest.main()

