"""Tests for environment-based configuration."""

import unittest

from inaturalist_harvestor.config import (
    ConfigurationError,
    Settings,
)

REQUIRED_ENV = {
    "INAT_USERNAME": "user",
    "INAT_PASSWORD": "password",
    "INAT_CLIENT_ID": "client-id",
    "INAT_CLIENT_SECRET": "client-secret",
    "DATABASE_URL": "postgresql://localhost/db",
}


class SettingsTest(unittest.TestCase):

    def test_defaults(self):
        settings = Settings.from_env(REQUIRED_ENV)

        self.assertEqual(settings.import_mode, "daily")
        self.assertEqual(settings.inaturalist.project_id, 183334)
        self.assertEqual(settings.inaturalist.per_page, 200)
        self.assertEqual(settings.checklistbank.request_delay, 0.2)
        self.assertEqual(
            settings.database.url, "postgresql://localhost/db"
        )

    def test_overrides(self):
        settings = Settings.from_env(
            {
                **REQUIRED_ENV,
                "IMPORT_MODE": "full",
                "INAT_PROJECT_ID": "999",
                "CHECKLISTBANK_REQUEST_DELAY": "0.5",
            }
        )

        self.assertEqual(settings.import_mode, "full")
        self.assertEqual(settings.inaturalist.project_id, 999)
        self.assertEqual(settings.checklistbank.request_delay, 0.5)

    def test_invalid_import_mode(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**REQUIRED_ENV, "IMPORT_MODE": "nope"})

    def test_missing_required_variable(self):
        env = dict(REQUIRED_ENV)
        del env["DATABASE_URL"]

        with self.assertRaises(ConfigurationError):
            Settings.from_env(env)


if __name__ == "__main__":
    unittest.main()
