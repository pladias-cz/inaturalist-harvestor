"""Repository for the iNaturalist taxon cache."""

from __future__ import annotations

from typing import Sequence

import psycopg
from psycopg.types.json import Jsonb

from ..models import GbifMatch, Taxon
from .connection import Database
from .schema import TAXA_TABLE

_UPSERT_SQL = f"""
    INSERT INTO {TAXA_TABLE} (
        id,
        name,
        rank,
        resolution_status,
        data
    )
    VALUES (
        %(id)s,
        %(name)s,
        %(rank)s,
        'pending',
        %(data)s
    )
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        rank = EXCLUDED.rank,
        data = EXCLUDED.data,
        updated_at = now()
"""

_SAVE_RESOLUTION_SQL = f"""
    UPDATE {TAXA_TABLE}
    SET
        gbif_taxon_key = %s,
        gbif_name = %s,
        col_id = %s,
        col_name = %s,
        col_rank = %s,
        resolution_status = %s,
        resolved_at = now(),
        data = COALESCE(data, '{{}}'::jsonb) || %s::jsonb,
        updated_at = now()
    WHERE id = %s
"""


class TaxonRepository:
    """Persists taxa and their GBIF resolutions."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def upsert_batch(
        self,
        conn: psycopg.Connection,
        taxa: Sequence[Taxon],
    ) -> None:
        """Ensure every iNaturalist taxon of the batch exists locally.

        Taxon resolution itself is deliberately NOT done here; the
        caller owns the transaction so that the taxon cache and the
        observations can be committed atomically.
        """
        if not taxa:
            return

        rows = [
            {
                "id": taxon.id,
                "name": taxon.name,
                "rank": taxon.rank,
                "data": Jsonb(taxon.data),
            }
            for taxon in taxa
        ]

        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, rows)

    def find_pending(self) -> list[Taxon]:
        """Return all taxa still awaiting GBIF resolution."""
        with self._database.connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    id,
                    name,
                    rank
                FROM {TAXA_TABLE}
                WHERE resolution_status = 'pending'
                ORDER BY id
                """
            )
            return [
                Taxon(id=id_, name=name, rank=rank, data={})
                for id_, name, rank in cur.fetchall()
            ]

    def save_resolution(
        self, taxon_id: int, match: GbifMatch
    ) -> None:
        """Store a GBIF Species Match result for a taxon."""
        with self._database.transaction() as conn, conn.cursor() as cur:
            cur.execute(
                _SAVE_RESOLUTION_SQL,
                (
                    match.usage_key,
                    match.scientific_name,
                    # Keep CoL ID separate from the GBIF key. The exact
                    # CoL extraction can be filled from the GBIF
                    # response / checklist data.
                    None,
                    None,
                    match.rank,
                    match.status,
                    Jsonb(
                        {
                            "gbif_match": match.data,
                            "gbif_match_type": match.match_type,
                            "gbif_confidence": match.confidence,
                            "gbif_usage_key": match.usage_key,
                            "gbif_accepted_usage_key":
                                match.accepted_usage_key,
                        }
                    ),
                    taxon_id,
                ),
            )
