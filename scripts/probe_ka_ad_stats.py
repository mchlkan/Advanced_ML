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

### Findings (2026-05-11; tested on both SneakerSupplierDE / 45852425
###            and the private account schmidt.leon2001@gmail.com / 152619387,
###            the latter with a live ACTIVE ad 3405575938 in scope)

- `GET /api/users/{uid}/ads.json` — list-my-ads, JAXB-JSON, paginated
  (`?page=&size=&_ver=1.16`; only `_ver=1.16` works — `2.0/1.20/1.30`
  → 500). **No view/watch field**, and `statistics=true` /
  `includeCounters=true` / `includeStatistics=true` / `counters=true`
  query flags are ignored. The KA app's "Meine Anzeigen" card *does*
  show `👁 N ♥ M`, so it fetches those from somewhere else.
- `GET /api/users/{uid}/ads/{adId}.json` (ad detail) — full ~6 KB
  object: price/title/description/category/attributes/location/pictures/
  displayoptions/ad-status/userBadges… **no view-count / watch-list-size
  / visit-count field anywhere**, even on a live ACTIVE ad.
- `GET /api/users/{uid}/profile.json` — works; account-level
  `counters.{historicalAds, onlineAds, followers, following}` +
  `userRatings`, `userBadges`, `analyticsId`. Not per-ad.
- **A family of endpoints that exist (HTTP 500, not 404) and the app
  almost certainly uses one of them — but every request shape tried
  returns 500 with an *empty* `<api-errors/>` (= unhandled server
  crash, not 400/401):**
    - `GET /api/users/{uid}/ads/counters.json`  (GET-only — POST → 405)
    - `GET /api/users/{uid}/ads/statistics.json`
    - `GET /api/users/{uid}/ads/visit-counters.json?ids=…`
    - `GET /api/users/{uid}/ads/watchlist-counters.json?ids=…`
    - `GET /api/users/{uid}/ads/visit-statistics.json`
  Tried: `?ids=`, `?adIds=`, `?adId=`, `?id=`, `?type=VISIT`,
  `?counterType=VISIT`, `?page=&size=`, `&_ver=1.16`, no params, and
  POST bodies (`{"ids":[…]}`, `{"adIds":[…]}`). All 500.
- Genuine 404s (don't exist): `…/ads/{adId}/{statistics,stats,visits,
  views,insights,counter,counters,visit-counter,visit-statistics,
  watchlist-counter}.json`, `/api/ads/{adId}/…`, `/api/users/{uid}/
  {statistics,insights,dashboard,ad-counters,visit-counters}.json`.
- `GET /api/users/{uid}/watchlist.json` exists — the *buyer-side*
  watchlist (ads this user favourited), not "who favourited my ad".

=> The view/watch data is real and the app shows it, but it's not
   exposed by any `GET` endpoint or response field reachable with the
   mobile JWT + tier-2 headers this codebase sends. The 500-family is
   the prime suspect — the endpoint needs something the request is
   missing (most likely a header the KA Android app sends). **Next
   step: mitmproxy / Charles on the KA Android app while it loads the
   "Meine Anzeigen" screen, then pin the exact endpoint + headers +
   params here.** (User said they'll provide the phone in a later
   session.) Until then, KA wardrobe sync is blocked.

### Side note: KA publish bugs surfaced while getting a live ad

- `build_ad_xml` emitted an empty `<shipping:shipping-options />` while
  ads declare `versand: ja` → KA `400 shippingOptions`. Fixed in
  `aefff21` — see `KA_DEFAULT_SHIPPING_OPTIONS` in
  `shared/listing_mappings.py` and the `shipping_options` payload key
  in `build_ad_xml`. Shipping-option preset ids: `HERMES_001/002/003`,
  `DHL_001/002` (id is an XML attribute on `<shipping:shipping-option>`).
- `_ka_attributes` sends `{prefix}.brand = slug(brand)`, but KA's brand
  attribute is an enum — non-enum slugs → `400 attributeMap[…brand]`.
  ("adidas" works; "blue_tomato" doesn't.) Unfixed — fall back to
  `"sonstige"` for unrecognised brands.
- COMMERCIAL accounts: ads in paid categories publish but land
  `ad-status: STALLED` pending payment (a step outside the mobile API).
  PRIVATE accounts post free → ACTIVE immediately. Use a private
  account for end-to-end publish testing.
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
