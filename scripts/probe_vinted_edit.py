"""Probe Vinted's mobile API for an edit endpoint on an existing live item.

Vinted's create flow already uses PUT /api/v2/item_upload/drafts/{id}
to attach the payload and POST /completion to publish. If item_id ==
draft_id (same URL namespace), the same PUT should work for editing
a live item. This script probes to confirm.

Run from repo root:
    python scripts/probe_vinted_edit.py <vinted_item_id>
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

from backend.integrations.vinted import (  # noqa: E402
    VintedClient,
    _mobile_headers,
    try_load_or_refresh,
)


def main(item_id: str) -> int:
    session, state = try_load_or_refresh()
    if state != "ready" or session is None:
        print(f"FAIL: Vinted session state={state!r}", file=sys.stderr)
        return 2

    client = VintedClient(session)
    print(f"Vinted session ready (domain={session.domain})")
    print(f"Probing item_id={item_id}\n")

    candidate_urls = [
        f"{client.base_url}/api/v2/item_upload/drafts/{item_id}",
        f"{client.base_url}/api/v2/items/{item_id}",
        f"{client.base_url}/api/v2/items/{item_id}/details",
    ]

    # OPTIONS first — discover allowed methods
    for url in candidate_urls:
        print(f"--- OPTIONS {url}")
        try:
            r = client.http.request(
                "OPTIONS", url, headers=_mobile_headers(client.session), timeout=30
            )
            print(f"  status: {r.status_code}")
            for h in ("Allow", "allow", "Access-Control-Allow-Methods"):
                if h in r.headers:
                    print(f"  {h}: {r.headers[h]}")
        except Exception as e:
            print(f"  error: {type(e).__name__}: {e}")
        print()

    # GET details to see body shape for edit
    print(f"--- GET /api/v2/items/{item_id}/details")
    r = client._get(f"/api/v2/items/{item_id}/details")
    print(f"  status: {r.status_code}, body length: {len(r.text)}")
    if r.status_code == 200:
        body = r.json()
        item = body.get("item", {})
        print(f"  can_edit: {item.get('can_edit')}, can_delete: {item.get('can_delete')}, "
              f"is_draft: {item.get('is_draft')}, is_hidden: {item.get('is_hidden')}, "
              f"is_closed: {item.get('is_closed')}")
        print(f"  item.id: {item.get('id')}, title: {item.get('title')!r}, "
              f"price: {item.get('price')!r}")
    else:
        print(f"  body: {r.text[:300]}")

    # Vinted's edit endpoint confirmed at PUT /api/v2/item_upload/items/{id}
    # (returns 400 validation_error listing required fields). Now: does a
    # price-only PUT preserve everything else (photos, brand, etc.), or
    # do we need to rebuild the full payload on every edit?
    #
    # Try several body shapes — minimal "title+price" first, then "price"
    # alone, then "price + price-meta". If any 200s, we have our answer.
    candidates = [
        ("PUT", f"/api/v2/item_upload/items/{item_id}",
         {"item": {"title": "Olive You T-Shirt", "price": "10.0", "currency": "EUR"}}),
        ("PUT", f"/api/v2/item_upload/items/{item_id}",
         {"item": {"price": "10.0"}}),
        ("PUT", f"/api/v2/item_upload/items/{item_id}",
         {"item": {"price": {"amount": "10.0", "currency_code": "EUR"}}}),
    ]
    for method, path, body in candidates:
        print(f"\n--- {method} {client.base_url}{path}")
        print(f"  body sent: {body}")
        try:
            r = client.http.request(
                method, f"{client.base_url}{path}",
                json=body,
                headers={**_mobile_headers(client.session), "content-type": "application/json; charset=UTF-8"},
                timeout=30,
            )
            print(f"  status: {r.status_code}")
            ctype = r.headers.get("content-type", "")
            if "application/json" in ctype:
                print(f"  body: {r.text[:600]}")
            else:
                print(f"  body: <{ctype}, {len(r.text)} chars>")
        except Exception as e:
            print(f"  error: {type(e).__name__}: {e}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    raise SystemExit(main(sys.argv[1]))
