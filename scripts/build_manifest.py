"""Build the multi-image training manifest.

Joins the raw scrape directories (which carry multiple photos per listing
plus CLIP type tags) with the canonical English parquets in ``data/`` to
produce a single Parquet with ``garment_path``, optional ``label_path``,
``target_text``, and the train/val/test split inherited from
``data/splits/*_ids.json``.

Vinted-only: the multi-image scraper (`vinted-lister`) only scrapes Vinted.
Kleinanzeigen listings stay out of this manifest and out of this training
round.

Run on the pod once the raw scrape zip is unzipped::

    python scripts/build_manifest.py \\
        --raw-root /workspace/data/raw \\
        --vinted-parquet data/vinted_clothing_combined.parquet \\
        --splits-dir data/splits \\
        --out /workspace/data/manifest.parquet

The script prefers ``items.jsonl.reclassified`` over ``items.jsonl`` when
both exist, so re-classified scrapes get used automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "shared"))
sys.path.insert(0, str(REPO_ROOT / "models"))
from prompts import get_prompt  # noqa: E402, F401  (kept for caller convenience)

_UNK_BRAND = "UNK"
_KA_PLACEHOLDER_BRAND = "Sonstige"

# CLIP tag values we care about. Real tags from Leon's scraper may include
# "garment", "label", "tag" (and variants); we treat "label" and "tag" as
# the same class for label-reading purposes.
_GARMENT_TAGS = {"garment", "clothing", "wear", "apparel"}
_LABEL_TAGS = {"label", "tag", "care_label", "care-label", "carelabel"}


# ---------------------------------------------------------------------------
# items.jsonl parsing — defensive about Leon's exact format
# ---------------------------------------------------------------------------

def _photo_records_from_obj(obj: dict, scrape_dir: Path) -> list[dict]:
    """Yield zero or more photo records from a single items.jsonl row.

    Supports both observed formats:

    A. one row per listing, ``images`` is a list of ``{"path": ..., "type": ...}``
    B. one row per (listing, photo): ``image`` (singular path) + ``type``

    Type field name fallbacks: ``type`` → ``clip_type`` → ``tag``.
    """
    listing_id = obj.get("id") or obj.get("listing_id")
    if listing_id is None:
        return []
    records = []

    # Format A — Leon's scraper writes `all_photos`; older guesses used `images`.
    images = obj.get("all_photos") or obj.get("images")
    if isinstance(images, list) and images:
        for img in images:
            if isinstance(img, str):
                # plain path, no type info
                path, typ = img, None
            elif isinstance(img, dict):
                path = img.get("path") or img.get("image") or img.get("file")
                typ = img.get("type") or img.get("clip_type") or img.get("tag")
            else:
                continue
            if not path:
                continue
            records.append({
                "listing_id": int(listing_id),
                "abs_path": str((scrape_dir / path).resolve()),
                "clip_type": _normalize_tag(typ),
            })
        return records

    # Format B
    path = obj.get("image") or obj.get("path") or obj.get("file")
    typ = obj.get("type") or obj.get("clip_type") or obj.get("tag")
    if path:
        records.append({
            "listing_id": int(listing_id),
            "abs_path": str((scrape_dir / path).resolve()),
            "clip_type": _normalize_tag(typ),
        })
    return records


def _normalize_tag(tag) -> Optional[str]:
    if tag is None:
        return None
    t = str(tag).strip().lower()
    if t in _GARMENT_TAGS:
        return "garment"
    if t in _LABEL_TAGS:
        return "label"
    return t  # pass through unknown tags so we can see what's there


def load_scrape_photos(scrape_dir: Path) -> pd.DataFrame:
    """Read items.jsonl[.reclassified] for one scrape into a flat photo table."""
    reclassified = scrape_dir / "items.jsonl.reclassified"
    primary = scrape_dir / "items.jsonl"
    src = reclassified if reclassified.exists() else primary
    if not src.exists():
        raise FileNotFoundError(
            f"no items.jsonl[.reclassified] in {scrape_dir}"
        )
    rows = []
    with open(src) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.extend(_photo_records_from_obj(obj, scrape_dir))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["scrape"] = scrape_dir.name
    df["source_file"] = src.name
    return df


def collapse_to_listings(photos: pd.DataFrame) -> pd.DataFrame:
    """One row per listing, picking the first garment + first label photo."""
    if photos.empty:
        return photos
    out = []
    for listing_id, grp in photos.groupby("listing_id", sort=False):
        garment_row = grp[grp["clip_type"] == "garment"].head(1)
        label_row = grp[grp["clip_type"] == "label"].head(1)
        if garment_row.empty:
            # No CLIP-tagged garment — fall back to the first photo. This is
            # how the no-CLIP scrape behaves before reclassification: every
            # row tagged "garment" so the head pick still works; this branch
            # only fires if there are no tags at all.
            garment_row = grp.head(1)
        out.append({
            "listing_id": int(listing_id),
            "garment_path": garment_row.iloc[0]["abs_path"],
            "label_path": (
                label_row.iloc[0]["abs_path"] if not label_row.empty else None
            ),
            "scrape": grp.iloc[0]["scrape"],
            "n_photos": len(grp),
        })
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Canonicalization (matches data_prep/build_splits.py + models/train_vlm.py)
# ---------------------------------------------------------------------------

def _canonicalize_brand(brand) -> str:
    if brand is None or (isinstance(brand, float) and pd.isna(brand)):
        return _UNK_BRAND
    if brand == _KA_PLACEHOLDER_BRAND:
        return _UNK_BRAND
    return brand


def _build_target_json(row) -> str:
    """JSON target string. Schema must match shared/prompts.py:get_prompt.

    Mirrors models.train_vlm._build_target_json — duplicated here to keep
    the manifest builder self-contained (importing from models triggers
    the heavyweight torch/transformers import chain).
    """
    brand = row.get("brand_canon")
    if brand in (None, "UNK") or (isinstance(brand, float) and pd.isna(brand)):
        brand = None
    size = row.get("size")
    if size in (None, "") or (isinstance(size, float) and pd.isna(size)):
        size = None
    obj = {
        "brand": brand,
        "category": row["category_en"],
        "condition": row["condition_en"],
        "color": row["color_en"],
        "size": size,
        "title": row["title_en"],
        "description": row["description_en"],
        "price_eur": float(row["price"]),
    }
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _enrich_with_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Add brand_canon + target_text columns to the canonical English DF."""
    out = df.copy()
    out["brand_canon"] = out["brand"].apply(_canonicalize_brand)
    out["target_text"] = out.apply(_build_target_json, axis=1)
    return out


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------

def _load_split_lookup(splits_dir: Path) -> dict[tuple[str, int], str]:
    """Map (platform, id) -> 'train' | 'val' | 'test' from the JSON id lists."""
    lookup: dict[tuple[str, int], str] = {}
    for split in ("train", "val", "test"):
        path = splits_dir / f"{split}_ids.json"
        if not path.exists():
            raise FileNotFoundError(f"missing split file: {path}")
        for entry in json.load(open(path)):
            lookup[(entry["platform"], int(entry["id"]))] = split
    return lookup


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def discover_scrapes(raw_root: Path) -> list[Path]:
    return sorted(p for p in raw_root.iterdir() if p.is_dir() and p.name.startswith("clothing_"))


def build_manifest(
    raw_root: Path,
    vinted_parquet: Path,
    splits_dir: Path,
    out_path: Path,
    min_target_chars: int = 10,
    max_target_chars: int = 2000,
) -> pd.DataFrame:
    print(f"raw_root: {raw_root}")
    scrapes = discover_scrapes(raw_root)
    print(f"  found {len(scrapes)} scrape dir(s):")
    for s in scrapes:
        print(f"    - {s.name}")

    photo_frames = []
    for s in scrapes:
        try:
            df = load_scrape_photos(s)
        except FileNotFoundError as e:
            print(f"  skipping {s.name}: {e}")
            continue
        photo_frames.append(df)
        type_counts = df["clip_type"].value_counts(dropna=False).to_dict()
        print(f"  {s.name}: {len(df)} photos, types={type_counts} "
              f"(from {df['source_file'].iloc[0]})")
    if not photo_frames:
        raise SystemExit("no photos loaded; check raw_root and items.jsonl format")
    photos = pd.concat(photo_frames, ignore_index=True)

    listings = collapse_to_listings(photos)
    print(f"\ncollapsed to {len(listings)} unique listings")
    print(f"  with label photo: {(listings['label_path'].notna()).sum()}")
    print(f"  garment-only:    {(listings['label_path'].isna()).sum()}")

    print(f"\nloading canonical text from {vinted_parquet}")
    vinted = pd.read_parquet(vinted_parquet)
    vinted = vinted[[
        "id", "platform", "title_en", "description_en", "category_en",
        "condition_en", "color_en", "brand", "size", "price",
    ]].copy()
    vinted["id"] = vinted["id"].astype(int)
    vinted = _enrich_with_targets(vinted)
    print(f"  vinted rows: {len(vinted)}")

    merged = listings.merge(
        vinted, left_on="listing_id", right_on="id", how="inner",
    )
    print(f"\njoined vinted×scrape: {len(merged)} rows")
    if len(merged) < 0.5 * min(len(listings), len(vinted)):
        print(f"  WARNING: low join rate. Listings only in scrape: "
              f"{len(listings) - len(merged)}, only in parquet: "
              f"{len(vinted) - len(merged)}")

    split_lookup = _load_split_lookup(splits_dir)
    merged["split"] = merged.apply(
        lambda r: split_lookup.get((r["platform"], int(r["id"])), None),
        axis=1,
    )
    unmapped = merged["split"].isna()
    if unmapped.any():
        print(f"  {unmapped.sum()} listings not in splits/*_ids.json — "
              f"assigning by hash(listing_id) % 100")
        # 0-79 train, 80-89 val, 90-99 test (matches build_splits.py philosophy
        # but is deterministic for new listings outside the locked test set)
        bucket = merged.loc[unmapped, "listing_id"].apply(lambda x: hash(int(x)) % 100)
        merged.loc[unmapped, "split"] = bucket.apply(
            lambda b: "train" if b < 80 else "val" if b < 90 else "test"
        )

    n_before = len(merged)
    target_lens = merged["target_text"].str.len()
    keep = (target_lens >= min_target_chars) & (target_lens <= max_target_chars)
    if (~keep).any():
        print(f"\ndropping {(~keep).sum()} rows with target_text outside "
              f"[{min_target_chars}, {max_target_chars}] chars")
    merged = merged[keep].reset_index(drop=True)

    cols = ["listing_id", "platform", "garment_path", "label_path",
            "target_text", "split", "scrape", "n_photos"]
    manifest = merged[cols].copy()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_parquet(out_path, index=False)
    print(f"\nwrote {out_path} ({len(manifest)} rows, dropped "
          f"{n_before - len(manifest)} from filters)")
    print(manifest["split"].value_counts().to_string())
    return manifest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--raw-root", type=Path, required=True,
                   help="Directory containing clothing_YYYY-MM-DD_HHMM/ subdirs.")
    p.add_argument("--vinted-parquet", type=Path,
                   default=REPO_ROOT / "data" / "vinted_clothing_combined.parquet",
                   help="Canonical vinted parquet (provides target_text source).")
    p.add_argument("--splits-dir", type=Path,
                   default=REPO_ROOT / "data" / "splits",
                   help="Directory with {train,val,test}_ids.json.")
    p.add_argument("--out", type=Path, required=True,
                   help="Output manifest parquet path.")
    p.add_argument("--min-target-chars", type=int, default=10)
    p.add_argument("--max-target-chars", type=int, default=2000)
    return p.parse_args()


def main():
    args = parse_args()
    build_manifest(
        raw_root=args.raw_root,
        vinted_parquet=args.vinted_parquet,
        splits_dir=args.splits_dir,
        out_path=args.out,
        min_target_chars=args.min_target_chars,
        max_target_chars=args.max_target_chars,
    )


if __name__ == "__main__":
    main()
