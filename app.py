import os
import sys
import time
from datetime import datetime, timedelta, timezone

import psycopg
import requests
from psycopg.types.json import Jsonb

# ============================================================================
# Configuration
# ============================================================================

INAT_SITE = "https://www.inaturalist.org"
INAT_API = "https://api.inaturalist.org/v2"

GBIF_API = "https://api.gbif.org/v1"

PROJECT_ID = 183334
PER_PAGE = 1000

IMPORT_MODE = os.getenv("IMPORT_MODE", "daily")

INAT_USERNAME = os.environ["INAT_USERNAME"]
INAT_PASSWORD = os.environ["INAT_PASSWORD"]
INAT_CLIENT_ID = os.environ["INAT_CLIENT_ID"]
INAT_CLIENT_SECRET = os.environ["INAT_CLIENT_SECRET"]

DATABASE_URL = os.environ["DATABASE_URL"]

# Daily import deliberately overlaps the previous period.
# This makes the import robust against timestamps / interrupted runs.
DAILY_OVERLAP = timedelta(days=3)

# Do not hammer external APIs.
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1"))

# GBIF Species Match requests.
GBIF_REQUEST_DELAY = float(
    os.getenv("GBIF_REQUEST_DELAY", "0.2")
)

USER_AGENT = os.getenv(
    "USER_AGENT",
    "pladias-inaturalist-importer/1.0"
)

# ============================================================================
# HTTP
# ============================================================================

session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT
})

# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------

def get_oauth_token():
    print("Obtaining OAuth token...", flush=True)

    response = session.post(
        f"{INAT_SITE}/oauth/token",
        data={
            "client_id": INAT_CLIENT_ID,
            "client_secret": INAT_CLIENT_SECRET,
            "grant_type": "password",
            "username": INAT_USERNAME,
            "password": INAT_PASSWORD,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    if "access_token" not in data:
        raise RuntimeError(
            f"No access_token in OAuth response: {data}"
        )

    return data["access_token"]


def get_jwt(oauth_token):
    print("Obtaining JWT...", flush=True)

    response = session.get(
        f"{INAT_SITE}/users/api_token",
        headers={
            "Authorization": f"Bearer {oauth_token}"
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    if "api_token" not in data:
        raise RuntimeError(
            f"No api_token in response: {data}"
        )

    return data["api_token"]

# ============================================================================
# Utility
# ============================================================================

def parse_datetime(value):

    if not value:
        return None

    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def parse_location(observation):

    location = observation.get("location")

    if not location:
        return None, None

    try:
        latitude, longitude = location.split(",")

        return float(latitude), float(longitude)

    except (ValueError, AttributeError):
        return None, None


# ----------------------------------------------------------------------
# PostgreSQL
# ----------------------------------------------------------------------

def save_taxa(conn, observations):

    """
    Ensure that every iNaturalist taxon occurring in the batch
    exists in inaturalist.taxa.

    Taxon resolution itself is deliberately NOT done here.
    """

    sql = """
        INSERT INTO inaturalist.taxa (
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

    taxa = {}

    for observation in observations:

        taxon = observation.get("taxon")

        if not taxon:
            continue

        taxon_id = taxon.get("id")

        if not taxon_id:
            continue

        taxa[taxon_id] = {
            "id": taxon_id,
            "name": taxon.get("name"),
            "rank": taxon.get("rank"),
            "data": Jsonb(taxon),
        }

    if not taxa:
        return

    with conn.cursor() as cur:
        cur.executemany(
            sql,
            taxa.values()
        )

def get_last_created_at(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT max(created_at)
            FROM gbif.inaturalist_records
        """)

        return cur.fetchone()[0]


# ----------------------------------------------------------------------
# iNaturalist
# ----------------------------------------------------------------------

def get_observations(jwt, created_after=None):
    """
    Download observations in batches of 1000.

    iNaturalist limits normal pagination to 10,000 records,
    therefore we use id_above as a cursor.

    created_after is used for daily incremental import.
    """

    last_id = 0
    imported = 0

    while True:

        params = {
            "project_id": PROJECT_ID,
            "per_page": PER_PAGE,
            "id_above": last_id,
            "order_by": "created_at",
            "order": "asc",
            "fields": "(id:!t,observed_on:!t,created_at:!t,species_guess:!t,taxon:(id:!t,name:!t,rank:!t),user:(id:!t,login:!t),latitude:!t,longitude:!t,positional_accuracy:!t,quality_grade:!t,geojson:(point:!t),private_geojson:(point:!t),location:!t,private_location:!t)",
        }

        if created_after is not None:
            params["created_d1"] = created_after.strftime(
                "%Y-%m-%d"
            )

        response = session.get(
            f"{INAT_API}/observations",
            params=params,
            headers={
                "Authorization": f"Bearer {jwt}"
            },
            timeout=120,
        )

        if response.status_code == 429:
            print(
                "Rate limited, sleeping 60 seconds...",
                flush=True
            )
            time.sleep(60)
            continue

        response.raise_for_status()

        payload = response.json()

        total = payload.get("total_results")

        observations = payload.get("results", [])

        if not observations:
            break

        save_observations(observations)

        imported += len(observations)

        last_id = observations[-1]["id"]

        print(
            f"Imported {imported}"
            f" / {total if total is not None else '?'}"
            f" — last id {last_id}",
            flush=True
        )

        if len(observations) < PER_PAGE:
            break

        time.sleep(
            REQUEST_DELAY
        )



# ----------------------------------------------------------------------
# UPSERT
# ----------------------------------------------------------------------

def save_observations(observations):

    sync_time = datetime.now(timezone.utc)

    sql = """
        INSERT INTO inaturalist.observations (
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
            positional_accuracy,

            quality_grade,
            species_guess,

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
            %(positional_accuracy)s,

            %(quality_grade)s,
            %(species_guess)s,

            true,
            %(sync_time)s,

            %(data)s,
            now()
        )

        ON CONFLICT (id) DO UPDATE SET

            created_at =
                EXCLUDED.created_at,

            updated_at =
                EXCLUDED.updated_at,

            observed_on =
                EXCLUDED.observed_on,

            taxon_id =
                EXCLUDED.taxon_id,

            taxon_name =
                EXCLUDED.taxon_name,

            taxon_rank =
                EXCLUDED.taxon_rank,

            user_id =
                EXCLUDED.user_id,

            user_login =
                EXCLUDED.user_login,

            latitude =
                EXCLUDED.latitude,

            longitude =
                EXCLUDED.longitude,

            positional_accuracy =
                EXCLUDED.positional_accuracy,

            quality_grade =
                EXCLUDED.quality_grade,

            species_guess =
                EXCLUDED.species_guess,

            in_project = true,

            last_seen_in_project =
                EXCLUDED.last_seen_in_project,

            data =
                EXCLUDED.data,

            imported_at =
                now()

        WHERE
            inaturalist.observations.updated_at
                IS DISTINCT FROM EXCLUDED.updated_at

            OR
            inaturalist.observations.in_project = false
    """

    rows = []

    for observation in observations:

        taxon = observation.get("taxon") or {}
        user = observation.get("user") or {}

        latitude, longitude = parse_location(
            observation
        )

        rows.append({

            "id":
                observation["id"],

            "created_at":
                parse_datetime(
                    observation.get("created_at")
                ),

            "updated_at":
                parse_datetime(
                    observation.get("updated_at")
                ),

            "observed_on":
                observation.get("observed_on"),

            "taxon_id":
                taxon.get("id"),

            "taxon_name":
                taxon.get("name"),

            "taxon_rank":
                taxon.get("rank"),

            "user_id":
                user.get("id"),

            "user_login":
                user.get("login"),

            "latitude":
                latitude,

            "longitude":
                longitude,

            "positional_accuracy":
                observation.get(
                    "positional_accuracy"
                ),

            "quality_grade":
                observation.get(
                    "quality_grade"
                ),

            "species_guess":
                observation.get(
                    "species_guess"
                ),

            "sync_time":
                sync_time,

            "data":
                Jsonb(observation),
        })

    if not rows:
        return

    with psycopg.connect(DATABASE_URL) as conn:

        # Taxon cache and observations are committed together.
        save_taxa(conn, observations)

        with conn.cursor() as cur:

            cur.executemany(
                sql,
                rows
            )

        conn.commit()


# ----------------------------------------------------------------------
# Full synchronization
# ----------------------------------------------------------------------

def mark_removed_observations(sync_started_at):

    """
    Any observation which wasn't encountered during the full
    synchronization is no longer in the project.
    """

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE gbif.inaturalist_records
                SET in_project = false
                WHERE
                    in_project = true
                    AND (
                        last_seen_in_project IS NULL
                        OR last_seen_in_project < %s
                    )
            """, (sync_started_at,))

            changed = cur.rowcount

        conn.commit()

    print(
        f"Marked {changed} observations as no longer "
        f"in project.",
        flush=True
    )


# ----------------------------------------------------------------------
# Daily
# ----------------------------------------------------------------------

def daily_import(jwt):

    with psycopg.connect(DATABASE_URL) as conn:
        last_created_at = get_last_created_at(conn)

    if last_created_at is None:

        print(
            "No existing data. Running full import.",
            flush=True
        )

        full_import(jwt)
        return

    created_after = (
        last_created_at - DAILY_OVERLAP
    )

    print(
        f"Daily import from {created_after.isoformat()}",
        flush=True
    )

    get_observations(
        jwt,
        created_after=created_after
    )


# ----------------------------------------------------------------------
# Full
# ----------------------------------------------------------------------

def full_import(jwt):

    sync_started_at = datetime.now(timezone.utc)

    print(
        f"Starting full synchronization at "
        f"{sync_started_at.isoformat()}",
        flush=True
    )

    get_observations(jwt)

    mark_removed_observations(sync_started_at)


# ============================================================================
# GBIF / CoL taxon resolution
# ============================================================================

def get_pending_taxa():

    with psycopg.connect(
        DATABASE_URL
    ) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    name,
                    rank
                FROM inaturalist.taxa
                WHERE resolution_status = 'pending'
                ORDER BY id
            """)

            return cur.fetchall()


def resolve_taxon(
    taxon_id,
    name,
    rank
):
    """
    Resolve an iNaturalist taxon using GBIF Species Match.

    The iNaturalist taxon ID itself is NOT sent as a GBIF key.
    The scientific name is used for matching.
    """

    params = {
        "name": name,
    }

    if rank:
        params["rank"] = rank

    response = session.get(
        f"{GBIF_API}/species/match",
        params=params,
        timeout=60,
    )

    if response.status_code == 429:

        print(
            "GBIF rate limit reached; "
            "sleeping 60 seconds...",
            flush=True
        )

        time.sleep(60)

        return resolve_taxon(
            taxon_id,
            name,
            rank
        )

    response.raise_for_status()

    return response.json()


def save_taxon_resolution(
    taxon_id,
    result
):

    match_type = result.get(
        "matchType"
    )

    confidence = result.get(
        "confidence"
    )

    usage_key = result.get(
        "usageKey"
    )

    accepted_usage_key = result.get(
        "acceptedUsageKey"
    )

    scientific_name = result.get(
        "scientificName"
    )

    rank = result.get(
        "rank"
    )

    # We consider an exact / fuzzy / higher-rank GBIF
    # match as "matched". No-match stays explicitly
    # "unmatched".
    if usage_key is not None:

        status = "matched"

    else:

        status = "unmatched"

    with psycopg.connect(
        DATABASE_URL
    ) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                UPDATE inaturalist.taxa

                SET
                    gbif_taxon_key = %s,
                    gbif_name = %s,
                    col_id = %s,
                    col_name = %s,
                    col_rank = %s,
                    resolution_status = %s,
                    resolved_at = now(),
                    data = COALESCE(data, '{}'::jsonb)
                        || %s::jsonb,
                    updated_at = now()

                WHERE id = %s
            """, (
                usage_key,
                scientific_name,

                # Keep CoL ID separate from GBIF key.
                #
                # The exact CoL extraction can be filled from
                # the GBIF response / checklist data.
                None,

                None,
                rank,

                status,

                Jsonb({
                    "gbif_match": result,
                    "gbif_match_type": match_type,
                    "gbif_confidence": confidence,
                    "gbif_usage_key": usage_key,
                    "gbif_accepted_usage_key":
                        accepted_usage_key,
                }),

                taxon_id,
            )
                         )

        conn.commit()


def resolve_pending_taxa():

    taxa = get_pending_taxa()

    print(
        f"{len(taxa)} pending taxon(s) "
        f"to resolve.",
        flush=True
    )

    for index, (
        taxon_id,
        name,
        rank
    ) in enumerate(taxa, start=1):

        print(
            f"Resolving {index}/{len(taxa)}: "
            f"{taxon_id} {name} ({rank})",
            flush=True
        )

        try:

            result = resolve_taxon(
                taxon_id,
                name,
                rank
            )

            save_taxon_resolution(
                taxon_id,
                result
            )

        except Exception as exc:

            print(
                f"Failed to resolve taxon "
                f"{taxon_id} {name}: {exc}",
                file=sys.stderr,
                flush=True
            )

        time.sleep(
            GBIF_REQUEST_DELAY
        )



# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():

    if IMPORT_MODE not in ("daily", "full"):
        raise RuntimeError(
            "IMPORT_MODE must be 'daily' or 'full'"
        )

    print(
        f"Starting iNaturalist import: {IMPORT_MODE}",
        flush=True
    )

    oauth_token = get_oauth_token()

    jwt = get_jwt(oauth_token)

    if IMPORT_MODE == "daily":
        daily_import(jwt)

    else:
        full_import(jwt)

    resolve_pending_taxa()

    print("Import finished.", flush=True)


if __name__ == "__main__":
    try:
        main()

    except Exception as e:
        print(
            f"ERROR: {e}",
            file=sys.stderr
        )
        raise