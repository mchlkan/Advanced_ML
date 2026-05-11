"""Probe KA's mobile API for per-ad view counts + watchlist (favourite) counts.

Goal: find out whether/how `api.kleinanzeigen.de` exposes the "X mal
aufgerufen" / watch-count numbers the KA mobile app shows on a seller's
own ads — i.e. the data a Kleinanzeigen-side "wardrobe sync" would need.

Read-only: only GET / OPTIONS, never POST/PUT/DELETE.

Run inside the EC2 container (where the KA session is materialised)::

    cat scripts/probe_ka_ad_stats.py | ssh -i ~/Downloads/Resell_Copilot.pem \
        ubuntu@13.49.21.29 'sudo docker exec -i resell-backend python3 -'

Optionally pass an ad id as the first arg to probe a specific live ad:

    ... 'sudo docker exec -i resell-backend python3 - <AD_ID>'

### Findings (2026-05-11, account SneakerSupplierDE / user 45852425)

- `GET /api/users/{uid}/ads.json` — list-my-ads, JAXB-JSON, paginated
  (`?page=&size=&_ver=1.16`). Status / field-selector / `statistics=true`
  query params are ignored. Account had **0 online ads** at probe time
  (`profile.json` → `counters.onlineAds = 0`), so no real ad to inspect.
- `GET /api/users/{uid}/profile.json` — works; returns
  `counters.{historicalAds, onlineAds, followers, following}` and
  `userRatings`, `userBadges`. (Account-level only — not per-ad.)
- `GET /api/users/{uid}/ads/statistics.json` and
  `GET /api/users/{uid}/ads/counters.json` — return **500** (JAXB error
  XML), *not* 404 → these routes exist but error on an empty account /
  without the right param. Strong candidates for the per-ad-stats
  surface; need an active ad (or the right query param) to see the
  response shape.
- `GET /api/users/{uid}/ads/{adId}/{statistics,stats,visits,views,
  insights}.json`, `/api/ads/{adId}/...`, `/api/users/{uid}/
  {statistics,insights,dashboard,ad-counters}.json` — all genuine
  404s (generic server `Allow` header) → don't exist.
- `GET /api/users/{uid}/watchlist.json` exists (the *buyer-side*
  watchlist of ads this user favourited — not "who favourited my ad");
  empty for this account.

=> Blocked on data availability: re-run this with at least one live KA
   listing to (a) dump `GET .../ads/{adId}.json` for a `view-count` /
   `watch-list-size` field and (b) re-hit the two 500-ing endpoints
   (`/ads/statistics.json`, `/ads/counters.json`) now that there's an
   ad in scope.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Works both inside the EC2 container (/app) and from a repo checkout.
for _p in ("/app", "/app/shared", "/app/models", str(Path(__file__).resolve().parents[1])):
    if _p not in sys.path and Path(_p).exists():
        sys.path.insert(0, _p)

# In-container the app materialises the session here; locally rely on the
# already-set env var (probe_ka_edit.py loads .env first if run that way).
if not os.environ.get("KA_SESSION_PATH") and Path("/app/data/ka_session.json").exists():
    os.environ["KA_SESSION_PATH"] = "/app/data/ka_session.json"

from backend.integrations.kleinanzeigen import (  # noqa: E402
    API_BASE,
    KAClient,
    try_load_or_refresh,
)

_STAT_KEY_RE = re.compile(
    r'"([a-zA-Z@:_\-]*(?:view|watch|hit|favorit|favourit|visit|count|impression|insight|stat)[a-zA-Z@:_\-]*)"',
    re.I,
)


def _show(label: str, resp, maxlen: int = 3000) -> None:
    print(f"\n=== {label} ===")
    print(
        f"  HTTP {resp.status_code}  ct={resp.headers.get('content-type')!r}  "
        f"allow={resp.headers.get('allow')!r}  len={len(resp.text)}"
    )
    body = resp.text
    if not body:
        print("  body: (empty)")
    elif len(body) > maxlen:
        print(f"  body[:{maxlen}]:", body[:maxlen], f"…(total {len(body)})")
    else:
        print("  body:", body)
    keys = sorted(set(_STAT_KEY_RE.findall(body)))
    if keys:
        print("  stat-like keys present:", keys)


def main() -> int:
    session, state = try_load_or_refresh()
    print(f"KA session state: {state}")
    if state != "ready" or session is None:
        print("  -> KA session not usable (needs SMS-MFA re-onboard). Stopping.")
        return 2
    print(f"  user_id={session.user_id} email={session.email} poster_type={session.poster_type}")

    client = KAClient(session)
    uid = session.user_id
    h = client._tier2_headers()

    _show(f"GET /api/users/{uid}/profile.json", client.http.get(f"{API_BASE}/api/users/{uid}/profile.json", headers=h, timeout=20))
    _show(f"GET /api/users/{uid}/ads.json", client.http.get(f"{API_BASE}/api/users/{uid}/ads.json?page=0&size=20&_ver=1.16", headers=h, timeout=20))

    # Real endpoints that 500 on an empty account — re-probe with/without an ad.
    for path in (f"/api/users/{uid}/ads/statistics.json", f"/api/users/{uid}/ads/counters.json"):
        _show(f"GET {path}", client.http.get(f"{API_BASE}{path}", headers=h, timeout=20))

    # Pick an ad id: CLI arg > first id in ads.json > none.
    ad_id = sys.argv[1] if len(sys.argv) > 1 else None
    if ad_id is None:
        try:
            ids = sorted(set(re.findall(r'"@?id"\s*:\s*"?(\d{6,})"?', client.http.get(f"{API_BASE}/api/users/{uid}/ads.json", headers=h, timeout=20).text)))
            ad_id = ids[0] if ids else None
        except Exception:
            ad_id = None
    if not ad_id:
        print("\n(no live KA ad available — re-run with an ad id once one is posted)")
        return 0

    print(f"\n--- probing ad {ad_id} ---")
    _show(f"GET /api/users/{uid}/ads/{ad_id}.json", client.http.get(f"{API_BASE}/api/users/{uid}/ads/{ad_id}.json", headers=h, timeout=20), maxlen=6000)
    for path in (
        f"/api/users/{uid}/ads/statistics.json?adId={ad_id}",
        f"/api/users/{uid}/ads/statistics.json?ids={ad_id}",
        f"/api/users/{uid}/ads/counters.json?adId={ad_id}",
        f"/api/users/{uid}/ads/{ad_id}/statistics.json",
        f"/api/users/{uid}/ads/{ad_id}/visit-statistics.json",
    ):
        _show(f"GET {path}", client.http.get(f"{API_BASE}{path}", headers=h, timeout=20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
