"""Tests for domain model parsing."""

import unittest
from datetime import datetime, timezone

from inaturalist_harvestor.models import (
    ColResolution,
    is_location_public,
    ColUsage,
    Observation,
    Taxon,
    parse_datetime,
    parse_location,
)


class ParseDatetimeTest(unittest.TestCase):

    def test_none(self):
        self.assertIsNone(parse_datetime(None))
        self.assertIsNone(parse_datetime(""))

    def test_z_suffix(self):
        parsed = parse_datetime("2024-05-01T12:30:00Z")
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.year, 2024)
        self.assertEqual(parsed.hour, 12)

    def test_offset(self):
        parsed = parse_datetime("2024-05-01T12:30:00+02:00")
        self.assertIsNotNone(parsed.tzinfo)


class ParseLocationTest(unittest.TestCase):

    def test_valid(self):
        self.assertEqual(
            parse_location("50.123,14.456"), (50.123, 14.456)
        )

    def test_missing(self):
        self.assertEqual(parse_location(None), (None, None))
        self.assertEqual(parse_location(""), (None, None))

    def test_invalid(self):
        self.assertEqual(parse_location("not,a,location"), (None, None))


class ObservationTest(unittest.TestCase):

    PAYLOAD = {
        "id": 123,
        "created_at": "2024-05-01T12:30:00Z",
        "updated_at": "2024-05-02T08:00:00Z",
        "observed_on": "2024-04-30",
        "species_guess": "Bee orchid",
        "taxon": {"id": 1, "name": "Ophrys apifera", "rank": "species"},
        "user": {"id": 42, "login": "naturalist"},
        "location": "50.1,14.5",
        "positional_accuracy": 20,
        "quality_grade": "research",
        "geoprivacy": None,
    }

    def test_from_api(self):
        observation = Observation.from_api(self.PAYLOAD)

        self.assertEqual(observation.id, 123)
        self.assertEqual(observation.observed_on, "2024-04-30")
        self.assertEqual(
            observation.updated_at,
            datetime(2024, 5, 2, 8, tzinfo=timezone.utc),
        )
        self.assertEqual(observation.latitude, 50.1)
        self.assertEqual(observation.longitude, 14.5)
        self.assertEqual(observation.quality_grade, "research")
        self.assertEqual(observation.species_guess, "Bee orchid")
        self.assertEqual(observation.user.login, "naturalist")
        self.assertTrue(observation.location_visibility)

        self.assertIsInstance(observation.taxon, Taxon)
        self.assertEqual(observation.taxon.id, 1)
        self.assertEqual(observation.taxon.name, "Ophrys apifera")

    def test_open_geoprivacy_is_public(self):
        # The API leaves geoprivacy out (null) for the default open
        # observations, both spellings are visible locations.
        for geoprivacy in (None, "", "open"):
            with self.subTest(geoprivacy=geoprivacy):
                observation = Observation.from_api(
                    {**self.PAYLOAD, "geoprivacy": geoprivacy}
                )

                self.assertTrue(observation.location_visibility)

    def test_hidden_geoprivacy_is_not_public(self):
        # Obscured observations carry randomised coordinates and
        # private ones none at all: neither may be shown publicly.
        for geoprivacy in ("obscured", "private"):
            with self.subTest(geoprivacy=geoprivacy):
                observation = Observation.from_api(
                    {**self.PAYLOAD, "geoprivacy": geoprivacy}
                )

                self.assertFalse(observation.location_visibility)

    def test_is_location_public_is_case_insensitive(self):
        self.assertFalse(is_location_public("Obscured"))
        self.assertTrue(is_location_public("OPEN"))

    def test_from_api_without_taxon(self):
        observation = Observation.from_api(
            {**self.PAYLOAD, "taxon": None, "location": None}
        )

        self.assertIsNone(observation.taxon)
        self.assertIsNone(observation.latitude)
        self.assertIsNone(observation.longitude)


class ColResolutionTest(unittest.TestCase):

    ACCEPTED = {
        "id": "L3KM",
        "name": "Battus philenor",
        "authorship": "(Linnaeus, 1771)",
        "rank": "species",
        "code": "zoological",
        "status": "accepted",
        "datasetKey": 316321,
        "label": "Battus philenor (Linnaeus, 1771)",
        "labelHtml": "<i>Battus philenor</i> (Linnaeus, 1771)",
        "parentId": "8HD3P",
    }

    SYNONYM = {
        "id": "XXXXX",
        "name": "Papilio philenor",
        "rank": "species",
        "status": "synonym",
    }

    def test_matched(self):
        resolution = ColResolution.from_related_response([self.ACCEPTED])

        self.assertEqual(resolution.col_id, "L3KM")
        self.assertEqual(resolution.col_name, "Battus philenor")
        self.assertEqual(resolution.col_rank, "species")
        self.assertEqual(resolution.status, "matched")

    def test_first_accepted_wins(self):
        resolution = ColResolution.from_related_response(
            [self.SYNONYM, self.ACCEPTED]
        )

        self.assertEqual(resolution.col_id, "L3KM")
        self.assertEqual(resolution.status, "matched")

    def test_unmatched_without_accepted(self):
        resolution = ColResolution.from_related_response(
            [self.SYNONYM]
        )

        self.assertIsNone(resolution.col_id)
        self.assertIsNone(resolution.col_name)
        self.assertIsNone(resolution.col_rank)
        self.assertEqual(resolution.status, "unmatched")

    def test_unmatched_empty(self):
        resolution = ColResolution.from_related_response([])

        self.assertIsNone(resolution.col_id)
        self.assertEqual(resolution.status, "unmatched")

    def test_usage_from_api(self):
        usage = ColUsage.from_api(self.ACCEPTED)

        self.assertEqual(usage.id, "L3KM")
        self.assertEqual(usage.name, "Battus philenor")
        self.assertEqual(usage.authorship, "(Linnaeus, 1771)")
        self.assertEqual(usage.rank, "species")
        self.assertEqual(usage.status, "accepted")
        self.assertEqual(usage.label, "Battus philenor (Linnaeus, 1771)")


if __name__ == "__main__":
    unittest.main()
