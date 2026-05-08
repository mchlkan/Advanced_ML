"""GET /listings and POST /listings/{id}/sold — inventory management."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from backend import db
from backend.schemas import ListingsResponse, ListingItem

router = APIRouter()


@router.get("/listings", response_model=ListingsResponse)
async def get_listings() -> ListingsResponse:
    rows = await db.get_all_listings()
    items: list[ListingItem] = []
    for row in rows:
        fields: dict = json.loads(row["english_fields"]) if row["english_fields"] else {}
        platforms = [p for p in (row["platforms"] or "").split(",") if p]
        image_name = Path(row["image_path"]).name
        items.append(ListingItem(
            id=row["id"],
            created_at=row["created_at"],
            image_url=f"/uploads/{image_name}",
            title=fields.get("title"),
            brand=fields.get("brand"),
            category=fields.get("category"),
            published_platforms=platforms,
        ))
    return ListingsResponse(listings=items)


@router.post("/listings/{listing_id}/sold", status_code=204, response_class=Response)
async def mark_sold(listing_id: str) -> Response:
    image_path = await db.delete_listing(listing_id)
    if image_path is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
    try:
        Path(image_path).unlink(missing_ok=True)
    except Exception:
        pass
    return Response(status_code=204)
