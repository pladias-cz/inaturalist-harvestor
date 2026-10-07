"""Physical table names used by the persistence layer.

The original single-file implementation referenced both the
"inaturalist" and "gbif" schemas for the same logical tables
(structure.sql defines them in the "gbif" schema). All SQL is
built from these constants so the mapping can be adjusted in a
single place.
"""

TAXA_TABLE = "gbif.inaturalist_taxa"
RECORDS_TABLE = "gbif.inaturalist_records"
