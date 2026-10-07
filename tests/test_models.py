"""Tests for domain model parsing."""

import unittest

from inaturalist_harvestor.models import (
    GbifMatch,
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
    }

    def test_from_api(self):
        observation = Observation.from_api(self.PAYLOAD)

        self.assertEqual(observation.id, 123)
        self.assertEqual(observation.observed_on, "2024-04-30")
        self.assertEqual(observation.latitude, 50.1)
        self.assertEqual(observation.longitude, 14.5)
        self.assertEqual(observation.quality_grade, "research")
        self.assertEqual(observation.species_guess, "Bee orchid")
        self.assertEqual(observation.user.login, "naturalist")

        self.assertIsInstance(observation.taxon, Taxon)
        self.assertEqual(observation.taxon.id, 1)
        self.assertEqual(observation.taxon.name, "Ophrys apifera")

    def test_from_api_without_taxon(self):
        observation = Observation.from_api(
            {**self.PAYLOAD, "taxon": None, "location": None}
        )

        self.assertIsNone(observation.taxon)
        self.assertIsNone(observation.latitude)
        self.assertIsNone(observation.longitude)


class GbifMatchTest(unittest.TestCase):

    def test_matched(self):
        match = GbifMatch.from_api(
            {
                "usageKey": 123,
                "scientificName": "Ophrys apifera",
                "matchType": "EXACT",
                "confidence": 98,
                "rank": "SPECIES",
            }
        )

        self.assertEqual(match.usage_key, 123)
        self.assertEqual(match.status, "matched")

    def test_unmatched(self):
        match = GbifMatch.from_api({"matchType": "NONE", "confidence": 0})

        self.assertIsNone(match.usage_key)
        self.assertEqual(match.status, "unmatched")


if __name__ == "__main__":
    unittest.main()
