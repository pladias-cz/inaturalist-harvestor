#!/usr/bin/env python3
"""Manual probe of the iNaturalist auth + API flow.

Reproduces exactly what ``inaturalist_harvestor`` does and prints
every request and response in full (secrets are masked):

  1. POST {site_url}/oauth/token      OAuth password grant -> access_token
  2. GET  {site_url}/users/api_token  Bearer access_token -> JWT api_token
  3. GET  {api_url}/observations      Bearer JWT -> one small page

Credentials are read from real env vars first, then from the .env
file in the repository root.

Each step also prints an equivalent curl command ready for
copy-paste. Long-lived credentials in the curl appear as shell
variables ($INAT_PASSWORD, …); short-lived Bearer tokens are real,
so the curl can be run immediately. Use --show-secrets to put
everything in the curl verbatim.

Usage:
    python scripts/probe_api.py [--per-page N] [--show-secrets]
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import shlex
import sys
from urllib.parse import urlencode

import requests

# Set from --show-secrets; controls masking everywhere.
SHOW_SECRETS = False

# OAuth grant fields replaced by shell variables in the curl command
# unless --show-secrets is given.
LONG_LIVED_KEYS = {"password", "client_secret", "client_id"}

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Same projection the real client requests (clients/inaturalist.py).
OBSERVATION_FIELDS = (
    "("
    "id:!t,observed_on:!t,created_at:!t,updated_at:!t,species_guess:!t,"
    "taxon:(id:!t,name:!t,rank:!t),"
    "user:(id:!t,login:!t),"
    "latitude:!t,longitude:!t,positional_accuracy:!t,quality_grade:!t,"
    "geojson:(point:!t),private_geojson:(point:!t),"
    "location:!t,private_location:!t,geoprivacy:!t"
    ")"
)

# Keys whose values must never be printed in full.
SECRET_KEYS = {
    "password",
    "client_secret",
    "client_id",
    "access_token",
    "api_token",
    "refresh_token",
    "authorization",
}


def load_env() -> dict[str, str]:
    """Real env vars win; .env fills in the rest."""
    import os

    env: dict[str, str] = {}
    dotenv = REPO_ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip("'\"")
    env.update(
        {k: v for k, v in os.environ.items() if k.startswith("INAT_")}
    )
    return env


def mask(key: str, value) -> str:
    text = str(value)
    if (
        not SHOW_SECRETS
        and key.lower() in SECRET_KEYS
        and len(text) > 8
    ):
        return f"{text[:4]}…{text[-4:]} (len={len(text)}, MASKED)"
    return text


def mask_secrets(obj):
    """Recursively mask secret values in a dict/list before printing."""
    if isinstance(obj, dict):
        return {
            k: (
                mask(k, v)
                if k.lower() in SECRET_KEYS
                else mask_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_secrets(item) for item in obj]
    return obj


def mask_authorization(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        if k.lower() == "authorization" and not SHOW_SECRETS:
            scheme, _, token = v.partition(" ")
            out[k] = (
                f"{scheme} {token[:8]}…{token[-8:]} (len={len(token)}, "
                "MASKED)" if token else v
            )
        else:
            out[k] = v
    return out


def build_curl(
    method: str,
    url: str,
    params: dict | None,
    data: dict | None,
    headers: dict[str, str],
) -> str:
    """Build an equivalent curl command for copy-pasting."""
    if params:
        url = f"{url}?{urlencode(params, doseq=True)}"

    parts = ["curl -sS"]
    if method != "GET":
        parts.append(f"-X {method}")
    parts.append(shlex.quote(url))

    for name in ("User-Agent", "Authorization"):
        value = headers.get(name)
        if value:
            parts.append(f"-H {shlex.quote(f'{name}: {value}')}")

    for key, value in (data or {}).items():
        if not SHOW_SECRETS and key.lower() in LONG_LIVED_KEYS:
            # Leave unquoted so the shell expands the variable.
            parts.append(f"--data-urlencode {key}=$INAT_{key.upper()}")
        else:
            parts.append(
                f"--data-urlencode {shlex.quote(f'{key}={value}')}"
            )

    return " \\\n       ".join(parts)


def call(
    session: requests.Session,
    step: str,
    method: str,
    url: str,
    **kwargs,
) -> requests.Response:
    """Perform a request and print the full call and response."""
    print(f"\n{'=' * 78}\n{step}\n{'=' * 78}")
    print(f"--> {method} {url}")
    for arg in ("params", "data", "json"):
        if kwargs.get(arg) is not None:
            print(
                f"    {arg}: "
                f"{json.dumps(mask_secrets(kwargs[arg]), default=str)}"
            )
    headers = dict(session.headers)
    headers.update(kwargs.get("headers") or {})
    print(f"    headers: {json.dumps(mask_authorization(headers))}")

    response = session.request(method, url, **kwargs)
    print(
        f"<-- {response.status_code} {response.reason} "
        f"in {response.elapsed.total_seconds():.2f}s"
    )
    interesting = {
        k: v
        for k, v in response.headers.items()
        if k.lower().startswith(("content-", "x-rate", "retry"))
    }
    print(f"    headers: {json.dumps(interesting)}")
    try:
        body = mask_secrets(response.json())
        text = json.dumps(body, indent=2, default=str)
        if len(text) > 8000:
            text = text[:8000] + f"\n… [truncated, total {len(text)} chars]"
        print(f"    body:\n{text}")
    except ValueError:
        print(f"    body (not JSON):\n{response.text[:2000]}")

    curl_headers = {"User-Agent": session.headers.get("User-Agent", "")}
    curl_headers.update(kwargs.get("headers") or {})
    print(
        "    copy-paste:\n       "
        + build_curl(
            method, url, kwargs.get("params"), kwargs.get("data"),
            curl_headers,
        )
    )

    response.raise_for_status()
    return response


def decode_jwt(token: str) -> dict:
    """Decode the payload of a JWT without verifying the signature."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe the iNaturalist OAuth -> JWT -> API flow."
    )
    parser.add_argument(
        "--per-page", type=int, default=3,
        help="number of observations to fetch in step 3 (default 3)",
    )
    parser.add_argument(
        "--show-secrets", action="store_true",
        help="print real credentials/tokens everywhere, including curl",
    )
    args = parser.parse_args()

    global SHOW_SECRETS
    SHOW_SECRETS = args.show_secrets

    env = load_env()
    missing = [
        k for k in
        ("INAT_USERNAME", "INAT_PASSWORD",
         "INAT_CLIENT_ID", "INAT_CLIENT_SECRET")
        if not env.get(k)
    ]
    if missing:
        print(f"Missing env vars / .env entries: {', '.join(missing)}")
        return 1

    site_url = env.get("INAT_SITE_URL", "https://www.inaturalist.org")
    api_url = env.get("INAT_API_URL", "https://api.inaturalist.org/v2")
    project_id = env.get("INAT_PROJECT_ID", "183334")
    user_agent = env.get(
        "USER_AGENT", "pladias-inaturalist-importer/1.0"
    )

    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    # 1) OAuth password grant (_obtain_oauth_token)
    oauth = call(
        session, "STEP 1 — POST /oauth/token (password grant)",
        "POST", f"{site_url}/oauth/token",
        data={
            "client_id": env["INAT_CLIENT_ID"],
            "client_secret": env["INAT_CLIENT_SECRET"],
            "grant_type": "password",
            "username": env["INAT_USERNAME"],
            "password": env["INAT_PASSWORD"],
        },
    ).json()
    oauth_token = oauth["access_token"]
    print(f"    access_token obtained (len={len(oauth_token)})")

    # 2) Exchange the OAuth token for the short-lived JWT
    jwt_resp = call(
        session, "STEP 2 — GET /users/api_token (Bearer OAuth token)",
        "GET", f"{site_url}/users/api_token",
        headers={"Authorization": f"Bearer {oauth_token}"},
    ).json()
    api_token = jwt_resp["api_token"]
    print(f"    api_token (JWT) obtained (len={len(api_token)})")
    print("    decoded JWT payload (signature NOT verified):")
    print(json.dumps(decode_jwt(api_token), indent=2))

    # 3) The actual API call with the JWT (iter_observation_batches)
    call(
        session,
        f"STEP 3 — GET /observations (Bearer JWT, project {project_id})",
        "GET", f"{api_url}/observations",
        params={
            "project_id": project_id,
            "per_page": args.per_page,
            "id_above": 0,
            "order_by": "id",
            "order": "asc",
            "fields": OBSERVATION_FIELDS,
        },
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=120,
    )

    print("\nAll three steps completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
