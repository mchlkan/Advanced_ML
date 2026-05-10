"""One-off discovery of KA category ids + art slugs for the 4 parent
categories the VLM emits on the Kleinanzeigen-side prompt.

The VLM (mchlkan/qwen3vl4b-resell-adapter-multi-v1) emits one of:
  - "Women's clothing"
  - "Men's clothing"
  - "Women's shoes"
  - "Men's shoes"

The runtime mapping table needs (a) a leaf KA category_id KA's submit
endpoint accepts and (b) the per-category required `art` attribute
slot. This script uses the live KA session to enumerate the category
tree and per-category metadata, then writes the findings to
docs/ka_category_probe.json so we can fill `KA_CATEGORY_TO_ID` /
`KA_ATTRS` empirically rather than guessing.

Run from repo root:
    python scripts/probe_ka_categories.py

Requires KA_SESSION_PATH in .env (the same value used by the backend).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Tiny inline .env loader — pulls KA_SESSION_PATH (and anything else)
# from the repo's .env without a python-dotenv dep.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(REPO_ROOT / ".env")

# Imports from backend depend on KA_SESSION_PATH being set above.
from backend.integrations.kleinanzeigen import (  # noqa: E402
    API_BASE,
    KAClient,
    try_load_or_refresh,
)


OUT_PATH = REPO_ROOT / "docs" / "ka_category_probe.json"

# German labels we expect for each canonical English category, in order
# of preference (most specific first). The walk picks the first match.
TARGETS: dict[str, list[str]] = {
    "Women's clothing": ["Damenbekleidung", "Damen Bekleidung", "Damen", "Bekleidung"],
    "Men's clothing":   ["Herrenbekleidung", "Herren Bekleidung", "Herren"],
    "Women's shoes":    ["Damenschuhe", "Damen Schuhe"],
    "Men's shoes":      ["Herrenschuhe", "Herren Schuhe"],
}

# Endpoints to try for the full category tree. KA's mobile API has
# moved between paths historically; we try in order and use the first
# that returns 200.
CATEGORY_TREE_PATHS = [
    "/api/categories.json",
    "/api/categories.json?_in=children",
    "/api/categories/0/children.json",
]


def _unwrap_value(x):
    """KA's JAXB-JSON wraps every scalar as {'value': <scalar>}. Recursively
    unwrap so we get plain strings/ints back."""
    if isinstance(x, dict) and set(x.keys()) == {"value"}:
        return _unwrap_value(x["value"])
    return x


def _walk(node: dict, parents: tuple[str, ...] = ()):
    """Recursively yield (id:int, name:str, parent_path:tuple, has_children:bool)."""
    if not isinstance(node, dict):
        return
    cid = _unwrap_value(node.get("id") or node.get("@id"))
    name = _unwrap_value(
        node.get("localized-name") or node.get("name") or node.get("@name") or ""
    )
    children = node.get("children") or node.get("category") or []
    if isinstance(children, dict):
        children = [children]
    yield {
        "id": int(cid) if cid not in (None, "") else None,
        "name": str(name) if name is not None else "",
        "parent_path": list(parents),
        "has_children": bool(children),
    }
    for child in children:
        if isinstance(child, dict) and "value" in child and isinstance(child["value"], dict):
            child = child["value"]
        yield from _walk(child, parents + (str(name),))


def _flatten_tree(payload: dict) -> list[dict]:
    """Pull the category root out of whatever envelope KA returns and
    flatten it into a list of nodes."""
    # JAXB-JSON envelope: top-level key is namespaced
    for k, v in payload.items():
        if isinstance(v, dict) and "value" in v:
            v = v["value"]
        if isinstance(v, dict):
            return list(_walk(v))
    return list(_walk(payload))


def _fetch_tree(client: KAClient) -> tuple[str, dict]:
    """Try the candidate endpoints in order; return (path, payload)
    of the first 200 OK."""
    last_err = None
    for path in CATEGORY_TREE_PATHS:
        url = f"{API_BASE}{path}"
        try:
            r = client.http.get(url, headers=client._tier2_headers(), timeout=30)
        except Exception as e:
            last_err = f"{path}: {type(e).__name__}: {e}"
            continue
        if r.status_code == 200:
            return path, r.json()
        last_err = f"{path}: HTTP {r.status_code} — {r.text[:200]}"
    raise RuntimeError(f"all category-tree endpoints failed; last: {last_err}")


def _fetch_metadata(client: KAClient, cat_id: int) -> dict:
    """Return parsed schema for category cat_id with the per-category
    attribute prefix + supported `art` values broken out."""
    url = f"{API_BASE}/api/ads/metadata/{cat_id}.json"
    r = client.http.get(url, headers=client._tier2_headers(), timeout=30)
    if r.status_code != 200:
        return {"status": r.status_code, "error": r.text[:300]}
    body = r.json()
    # Unwrap JAXB envelope: top key is the namespaced "ad", value lives
    # under .value (.value.attributes.attribute is the attr list).
    ad_root = list(body.values())[0]
    ad_value = ad_root.get("value", {}) if isinstance(ad_root, dict) else {}
    raw_attrs = ad_value.get("attributes", {}).get("attribute", []) or []
    if isinstance(raw_attrs, dict):
        raw_attrs = [raw_attrs]

    attributes: list[dict] = []
    prefix: str | None = None
    art_values: list[str] = []
    for a in raw_attrs:
        name = a.get("name", "")
        if not isinstance(name, str):
            continue
        if "." in name and prefix is None:
            prefix = name.split(".", 1)[0]
        sup = a.get("supported-value", []) or []
        if isinstance(sup, dict):
            sup = [sup]
        sup_values = [sv.get("value") for sv in sup if isinstance(sv, dict)]
        attributes.append({
            "name": name,
            "write": a.get("write"),
            "label": a.get("localized-label"),
            "supported_count": len(sup_values),
            # Inline values for short enums; brand has 2400+ so cap.
            "supported_values": sup_values if len(sup_values) <= 30 else sup_values[:30] + ["...(truncated)"],
        })
        if name.endswith(".art"):
            art_values = sup_values
    return {
        "status": 200,
        "prefix": prefix,
        "art_values": art_values,
        "attributes": attributes,
    }


def main() -> int:
    session, state = try_load_or_refresh()
    if state != "ready" or session is None:
        print(f"FAIL: KA session state={state!r}; complete onboarding/login first", file=sys.stderr)
        return 2

    client = KAClient(session)
    print(f"KA session ready (user_id={session.user_id}, email={session.email})")

    print("Fetching category tree...")
    try:
        used_path, payload = _fetch_tree(client)
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 3
    nodes = _flatten_tree(payload)
    print(f"  -> via {used_path} ({len(nodes)} nodes)")

    # Build name -> nodes index for fast matching, case-insensitive
    by_name: dict[str, list[dict]] = {}
    for n in nodes:
        if n["id"] is None:
            continue
        key = (n["name"] or "").strip().lower()
        by_name.setdefault(key, []).append(n)

    findings: dict[str, dict] = {}
    for english, candidates in TARGETS.items():
        matches: list[dict] = []
        for de in candidates:
            for hit in by_name.get(de.strip().lower(), []):
                matches.append({**hit, "matched_label": de})
        # Deduplicate by id, preserve order
        seen: set[int] = set()
        deduped: list[dict] = []
        for m in matches:
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            deduped.append(m)

        # Pick "best": prefer leaves (no children) so KA accepts the publish.
        leaves = [m for m in deduped if not m["has_children"]]
        best = (leaves or deduped or [None])[0]

        meta = None
        if best and best["id"]:
            print(f"  {english!r:<22} -> id={best['id']} name={best['name']!r} leaf={not best['has_children']}")
            try:
                meta = _fetch_metadata(client, best["id"])
                print(f"     prefix={meta.get('prefix')!r}  art_values={meta.get('art_values')}")
            except Exception as e:
                meta = {"error": f"{type(e).__name__}: {e}"}
        else:
            print(f"  {english!r:<22} -> NO MATCH (looked for: {candidates})")

        findings[english] = {
            "candidates": deduped,
            "best": best,
            "metadata": meta,
        }

    out = {
        "probed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "category_tree_path": used_path,
        "categories": findings,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nWrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
