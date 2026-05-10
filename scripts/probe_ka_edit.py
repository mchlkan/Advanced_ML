"""Probe KA's mobile API for an edit endpoint on an existing ad.

Goals:
  1. Confirm the GET shape of an individual ad
     (`/api/users/{user_id}/ads/{ad_id}.json`).
  2. Confirm OPTIONS to discover Allow methods (PUT? PATCH?).
  3. (Read-only) print what a PUT body would look like for a price
     change — does NOT actually mutate the ad.

Run from repo root:
    python scripts/probe_ka_edit.py <kleinanzeigen_ad_id>

If no ad_id is given, the script lists the most recent successful KA
publishes from the local DB on EC2 — but for safety this script
expects you to pass the id explicitly.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(REPO_ROOT / ".env")

from backend.integrations.kleinanzeigen import (  # noqa: E402
    API_BASE,
    KAClient,
    try_load_or_refresh,
)


def main(ad_id: str) -> int:
    session, state = try_load_or_refresh()
    if state != "ready" or session is None:
        print(f"FAIL: KA session state={state!r}", file=sys.stderr)
        return 2

    client = KAClient(session)
    print(f"KA session ready (user_id={session.user_id}, email={session.email})")
    print(f"Probing ad_id={ad_id}\n")

    # Two URL shapes to try — KA's mobile API has used both historically.
    candidate_urls = [
        f"{API_BASE}/api/users/{session.user_id}/ads/{ad_id}.json",
        f"{API_BASE}/api/ads/{ad_id}.json",
    ]

    for url in candidate_urls:
        print(f"--- GET {url}")
        r = client.http.get(url, headers=client._tier2_headers(), timeout=30)
        print(f"  status: {r.status_code}")
        if r.status_code == 200:
            print(f"  body length: {len(r.text)}")
            body = r.json()
            # Unwrap JAXB envelope
            ad_root = list(body.values())[0] if body else {}
            ad_value = ad_root.get("value", {}) if isinstance(ad_root, dict) else {}
            print(f"  top-level ad keys (first 20): {list(ad_value.keys())[:20]}")
            # Look for price / status / id markers
            for key in ("price", "ad-status", "id", "category", "last-user-edit-date"):
                if key in ad_value:
                    print(f"    {key}: {json.dumps(ad_value[key], ensure_ascii=False)[:300]}")
            # Save raw for offline inspection
            out_path = REPO_ROOT / "docs" / f"_ka_ad_{ad_id}_raw.json"
            out_path.write_text(json.dumps(body, indent=2, ensure_ascii=False))
            print(f"  saved raw body to {out_path}")
            break
        else:
            print(f"  body: {r.text[:300]}")

    print()

    # OPTIONS to discover allowed write methods
    for url in candidate_urls:
        print(f"--- OPTIONS {url}")
        r = client.http.request(
            "OPTIONS", url, headers=client._tier2_headers(), timeout=30
        )
        print(f"  status: {r.status_code}")
        allow = r.headers.get("Allow") or r.headers.get("allow")
        if allow:
            print(f"  Allow: {allow}")
        cors_methods = r.headers.get("Access-Control-Allow-Methods")
        if cors_methods:
            print(f"  Access-Control-Allow-Methods: {cors_methods}")
        print()

    # Try a HEAD as an extra hint
    print(f"--- HEAD {candidate_urls[0]}")
    r = client.http.request("HEAD", candidate_urls[0], headers=client._tier2_headers(), timeout=30)
    print(f"  status: {r.status_code}")
    print(f"  headers (subset): {dict((k, v) for k, v in r.headers.items() if k.lower() in {'allow', 'access-control-allow-methods', 'last-modified'})}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    raise SystemExit(main(sys.argv[1]))
