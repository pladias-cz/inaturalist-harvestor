"""Tests for the daily / full import orchestration."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

from inaturalist_harvestor.config import Settings
from inaturalist_harvestor.models import Observation, Taxon, User

try:
    from inaturalist_harvestor.services.import_service import (
        ObservationImportService,
    )
except ImportError as error:
    # The service pulls in the database layer which needs psycopg.
    MISSING_DEPENDENCY = str(error)
else:
    MISSING_DEPENDENCY = None

REQUIRED_ENV = {
    "INAT_USERNAME": "user",
    "INAT_PASSWORD": "password",
    "INAT_CLIENT_ID": "client-id",
    "INAT_CLIENT_SECRET": "client-secret",
    "DATABASE_URL": "postgresql://localhost/db",
}


def make_settings(max_removal_ratio: float = 0.2) -> Settings:
    settings = Settings.from_env(REQUIRED_ENV)
    return replace(settings, max_removal_ratio=max_removal_ratio)


def make_observation(id_: int) -> Observation:
    return Observation(
        id=id_,
        created_at=datetime(2024, 5, 1, 12, tzinfo=timezone.utc),
        updated_at=datetime(2024, 5, 2, 12, tzinfo=timezone.utc),
        observed_on="2024-04-30",
        taxon=Taxon(id=1, name="Ophrys apifera", rank="species", data={}),
        user=User(id=42, login="naturalist"),
        latitude=50.1,
        longitude=14.5,
        positional_accuracy=20,
        quality_grade="research",
        species_guess="Bee orchid",
        data={"id": id_},
    )


class StubDatabase:
    """Hands out a dummy connection; transactions are no-ops."""

    @contextmanager
    def transaction(self) -> Iterator[object]:
        yield object()


class StubTaxa:
    def __init__(self) -> None:
        self.batches: list[list[Taxon]] = []

    def upsert_batch(self, conn: Any, taxa: Sequence[Taxon]) -> None:
        self.batches.append(list(taxa))


class StubObservations:
    """Records what was stored, answers the removal-pass counters."""

    def __init__(
        self,
        total: int = 0,
        candidates: int = 0,
        last_created_at: datetime | None = None,
    ) -> None:
        self._total = total
        self._candidates = candidates
        self._last_created_at = last_created_at
        self.batches: list[list[Observation]] = []
        self.sync_times: list[datetime] = []
        self.marked_at: list[datetime] = []

    def find_last_created_at(self) -> datetime | None:
        return self._last_created_at

    def upsert_batch(
        self,
        conn: Any,
        observations: Sequence[Observation],
        sync_time: datetime,
    ) -> None:
        self.batches.append(list(observations))
        self.sync_times.append(sync_time)

    def count_records(self) -> int:
        return self._total

    def count_not_seen_since(
        self, sync_started_at: datetime
    ) -> int:
        return self._candidates

    def mark_missing_as_removed(
        self, sync_started_at: datetime
    ) -> int:
        self.marked_at.append(sync_started_at)
        return self._candidates

    @property
    def removal_passes(self) -> int:
        return len(self.marked_at)


class StubClient:
    """Replays canned observation batches."""

    def __init__(
        self, batches: Sequence[Sequence[Observation]]
    ) -> None:
        self._batches = [list(batch) for batch in batches]
        self.created_after: list[Any] = []

    def iter_observation_batches(
        self, created_after: datetime | None = None
    ) -> Iterator[list[Observation]]:
        self.created_after.append(created_after)
        for batch in self._batches:
            yield batch


@unittest.skipIf(
    MISSING_DEPENDENCY is not None,
    MISSING_DEPENDENCY or "missing dependency",
)
class ImportServiceTest(unittest.TestCase):

    def make_service(
        self,
        batches: Sequence[Sequence[Observation]],
        total: int = 0,
        candidates: int = 0,
        last_created_at: datetime | None = None,
        max_removal_ratio: float = 0.2,
    ) -> tuple[
        ObservationImportService,
        StubClient,
        StubTaxa,
        StubObservations,
    ]:
        observations = StubObservations(
            total=total,
            candidates=candidates,
            last_created_at=last_created_at,
        )
        taxa = StubTaxa()
        client = StubClient(batches)
        service = ObservationImportService(
            settings=make_settings(max_removal_ratio),
            database=StubDatabase(),
            client=client,
            taxa=taxa,
            observations=observations,
        )
        return service, client, taxa, observations


class FullImportTest(ImportServiceTest):

    def test_stores_observations_together_with_their_taxa(self):
        service, _, taxa, observations = self.make_service(
            [[make_observation(1), make_observation(2)]],
            total=10,
            candidates=0,
        )

        service.run_full()

        self.assertEqual(
            [len(batch) for batch in observations.batches], [2]
        )
        self.assertEqual(
            [taxon.id for batch in taxa.batches for taxon in batch], [1]
        )
        self.assertEqual(len(observations.sync_times), 1)

    def test_removal_pass_runs_after_a_complete_harvest(self):
        service, _, _, observations = self.make_service(
            [[make_observation(1)]], total=10, candidates=1
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 1)

    def test_removal_pass_is_skipped_on_an_empty_harvest(self):
        # An empty feed must never flag the whole table as removed.
        service, _, _, observations = self.make_service(
            [], total=10, candidates=10
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 0)

    def test_removal_pass_is_skipped_beyond_the_ratio(self):
        # Guards against a harvest which silently stopped early: the
        # pass would flag half of the table while the run enumerated
        # a single observation.
        service, _, _, observations = self.make_service(
            [[make_observation(1)]], total=10, candidates=5
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 0)

    def test_removal_pass_follows_a_harvest_larger_than_the_loss(self):
        # A project may legitimately lose a large share of its
        # observations at once when the harvest enumerated clearly
        # more observations than the pass would flag.
        service, _, _, observations = self.make_service(
            [
                [
                    make_observation(id_)
                    for id_ in range(1, 51)
                ]
            ],
            total=100,
            candidates=30,
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 1)

    def test_removal_pass_prunes_a_small_project(self):
        # Small tables must not be frozen by the ratio of a handful of
        # rows; the harvest still saw as many observations as remain.
        service, _, _, observations = self.make_service(
            [[make_observation(1)]], total=2, candidates=1
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 1)

    def test_removal_pass_allows_the_configured_ratio(self):
        service, _, _, observations = self.make_service(
            [[make_observation(1)]],
            total=10,
            candidates=2,
            max_removal_ratio=0.2,
        )

        service.run_full()

        self.assertEqual(observations.removal_passes, 1)

    def test_removal_pass_uses_the_start_of_the_run(self):
        service, _, _, observations = self.make_service(
            [[make_observation(1)]], total=10, candidates=0
        )

        before = datetime.now(timezone.utc)
        service.run_full()
        after = datetime.now(timezone.utc)

        # The timestamp must not postdate the harvested batches,
        # otherwise observations seen by this very run would be flagged
        # as gone; and it must predate them so that everything the run
        # enumerated survives the removal pass.
        self.assertEqual(len(observations.marked_at), 1)
        self.assertLessEqual(before, observations.marked_at[0])
        self.assertLess(observations.marked_at[0], after)
        self.assertLessEqual(
            observations.marked_at[0], observations.sync_times[0]
        )


class DailyImportTest(ImportServiceTest):

    def test_overlaps_the_previous_period(self):
        last_created_at = datetime(2024, 5, 10, tzinfo=timezone.utc)
        service, client, _, observations = self.make_service(
            [[make_observation(1)]],
            last_created_at=last_created_at,
        )

        service.run_daily()

        self.assertEqual(
            client.created_after,
            [last_created_at - timedelta(days=3)],
        )
        # An incremental run never enumerates the whole project, so it
        # must never flag anything as removed.
        self.assertEqual(observations.removal_passes, 0)

    def test_falls_back_to_a_full_import_when_empty(self):
        service, client, _, observations = self.make_service(
            [[make_observation(1)]],
            last_created_at=None,
            total=10,
            candidates=0,
        )

        service.run_daily()

        self.assertEqual(client.created_after, [None])
        self.assertEqual(observations.removal_passes, 1)


if __name__ == "__main__":
    unittest.main()



