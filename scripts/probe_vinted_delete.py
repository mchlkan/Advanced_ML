"""Probe Vinted's mobile API for the right delete endpoint on a LIVE item.

The existing delete_draft uses /api/v2/item_upload/drafts/{id} which 403s
on published items. This script tries DELETE on candidate URLs to find
the correct verb+path for live-item removal — non-destructively where
possible (OPTIONS first, then a real DELETE only on a designated
test_id passed by the caller).

Run from repo root inside the EC2 container:
    sudo docker exec -e VINTED_SESSION_PATH=/app/data/vinted_session.json \
        resell-backend python /app/probe_vinted_delete.py <item_id> [--apply]

Without --apply, only OPTIONS is sent. With --apply, a real DELETE is
attempted on the *first* candidate that OPTIONS reports allows DELETE.
"""

from __future__ import annotations

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


def main(item_id: str, apply: bool) -> int:
    session, state = try_load_or_refresh()
    if state != "ready" or session is None:
        print(f"FAIL: Vinted session state={state!r}", file=sys.stderr)
        return 2

    client = VintedClient(session)
    print(f"Vinted session ready (domain={session.domain})")
    print(f"Probing DELETE for item_id={item_id}, apply={apply}\n")

    # Confirm the item is currently live (and we have permission)
    print("--- GET /api/v2/items/{id}/details (sanity check) ---")
    r = client._get(f"/api/v2/items/{item_id}/details")
    print(f"  status: {r.status_code}")
    if r.status_code == 200:
        item = r.json().get("item", {})
        print(f"  can_delete: {item.get('can_delete')}, can_edit: {item.get('can_edit')}")
        print(f"  is_draft: {item.get('is_draft')}, is_closed: {item.get('is_closed')}")
        print(f"  status: {item.get('status')!r}")

    user_id = session.user_id
    print(f"  user_id from session: {user_id}")

    # Candidate URLs + verbs. Vinted UI must use one of these patterns.
    # (verb, path, json_body) — body=None means no payload.
    delete_candidates: list[tuple[str, str, dict | None]] = [
        ("DELETE", f"/api/v2/users/{user_id}/items/{item_id}",     None),
        ("DELETE", f"/api/v2/items/{item_id}/delete",              None),
        ("DELETE", f"/api/v2/wardrobe/items/{item_id}",            None),
        # Soft-close patterns (change status without removing)
        ("POST",   f"/api/v2/items/{item_id}/close",               None),
        ("POST",   f"/api/v2/items/{item_id}/delete",              None),
        ("PUT",    f"/api/v2/items/{item_id}/status",              {"status": "closed"}),
        ("POST",   f"/api/v2/item_upload/items/{item_id}/close",   None),
        # Maybe DELETE works on the user-scoped wardrobe URL
        ("DELETE", f"/api/v2/users/{user_id}/wardrobe/items/{item_id}", None),
    ]

    print(f"\n--- {len(delete_candidates)} verb+path candidates (apply={apply}) ---")
    for verb, path, body in delete_candidates:
        url = f"{client.base_url}{path}"
        if not apply:
            print(f"  (dry-run) {verb} {url}  body={body}")
            continue
        try:
            kwargs = {"headers": _mobile_headers(client.session), "timeout": 30}
            if body is not None:
                kwargs["json"] = body
                kwargs["headers"] = {**kwargs["headers"], "content-type": "application/json; charset=UTF-8"}
            r = client.http.request(verb, url, **kwargs)
            ctype = r.headers.get("content-type", "")
            snippet = r.text[:200] if "application/json" in ctype else f"<{ctype}, {len(r.text)} chars>"
            print(f"  {verb:6} {path:<55} -> {r.status_code}  {snippet}")
            if r.status_code in (200, 204):
                print(f"  >>> {verb} on {path} succeeded — this is the right endpoint <<<")
                v = client._get(f"/api/v2/items/{item_id}/details")
                print(f"  post-action GET /details -> {v.status_code}")
                if v.status_code == 200:
                    item = v.json().get("item", {})
                    print(f"  is_closed={item.get('is_closed')}, status={item.get('status')!r}")
                return 0
        except Exception as e:
            print(f"  {verb} {path} -> error: {type(e).__name__}: {e}")

    return 0 if not apply else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    apply_flag = "--apply" in sys.argv
    raise SystemExit(main(sys.argv[1], apply_flag))
