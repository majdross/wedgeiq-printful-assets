#!/usr/bin/env python3
"""Stage 5 Option B: create an unpublished Printful My Product directly via v2 API.

Goal
----
Bypass one-time manual Product Template creation. This script creates an
UNPUBLISHED My Product directly from the approved Printful catalog product.
Artwork is intentionally a placeholder so the final WedgeIQ artwork can still
be adjusted manually in Printful.

Safety
------
- Default is DRY RUN.
- Start with ONE product (hoodie) before bulk creation.
- Use --create to make the API write.
- The script does NOT publish to Shopify.

Requires
--------
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Examples
--------
  python3 scripts/stage5_direct_my_product_create.py --only hoodie
  python3 scripts/stage5_direct_my_product_create.py --only hoodie --create

Optional overrides
------------------
  --placement front
  --technique dtfilm
  --artwork-url https://.../placeholder.png

Outputs
-------
  stage5_direct_product_results.json
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.printful.com"
QUEUE_PATH = Path("stage3_product_queue.json")
PLAN_PATH = Path("product_catalog_plan.json")
OUT_PATH = Path("stage5_direct_product_results.json")

DEFAULT_ARTWORK_URL = (
    "https://raw.githubusercontent.com/majdross/wedgeiq-printful-assets/main/"
    "01_PRINTFUL_UPLOAD/TEE_DTG/FLIGHT_IT_NAVY_3600px.png"
)

PLACEMENT_PRIORITY = [
    "embroidery_chest_left",
    "embroidery_chest_center",
    "front",
    "front_large",
    "front_dtf",
]


def request_json(method, path, token, store_id=None, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if store_id:
        headers["X-PF-Store-Id"] = str(store_id)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise


def load_json(path):
    if not path.exists():
        raise SystemExit(f"Missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def get_catalog_product(token, product_id):
    return request_json(
        "GET",
        f"/v2/catalog-products/{product_id}?selling_region_name=north_america",
        token,
    ).get("data", {})


def placement_name(p):
    return p.get("placement") or p.get("id") or p.get("name")


def placement_techniques(p):
    values = []
    if p.get("technique"):
        values.append(p.get("technique"))
    if p.get("technique_key"):
        values.append(p.get("technique_key"))
    for item in p.get("techniques", []) or []:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            values.append(item.get("key") or item.get("technique") or item.get("id"))
    return [v for v in values if v]


def choose_placement_and_technique(product, preferences, forced_placement=None, forced_technique=None):
    placements = product.get("placements", []) or []
    techniques = product.get("techniques", []) or []
    product_techniques = []
    for t in techniques:
        if isinstance(t, str):
            product_techniques.append(t)
        elif isinstance(t, dict):
            product_techniques.append(t.get("key") or t.get("id"))
    product_techniques = [x for x in product_techniques if x]

    if forced_placement and forced_technique:
        return forced_placement, forced_technique

    preferred_technique = forced_technique
    if not preferred_technique:
        for pref in preferences:
            if pref in product_techniques:
                preferred_technique = pref
                break
        if not preferred_technique and product_techniques:
            preferred_technique = product_techniques[0]

    candidates = []
    for p in placements:
        name = placement_name(p)
        if not name:
            continue
        ptech = placement_techniques(p)
        compatible = not ptech or not preferred_technique or preferred_technique in ptech
        if compatible:
            candidates.append(name)

    if forced_placement:
        selected_placement = forced_placement
    else:
        selected_placement = None
        for priority in PLACEMENT_PRIORITY:
            if priority in candidates:
                selected_placement = priority
                break
        if not selected_placement and candidates:
            selected_placement = candidates[0]
        if not selected_placement:
            # Common fallback for catalog products whose placement list is sparse.
            selected_placement = "front"

    if not preferred_technique:
        raise SystemExit("Could not determine a technique. Use --technique explicitly.")

    return selected_placement, preferred_technique


def existing_results():
    if not OUT_PATH.exists():
        return []
    try:
        return json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_results(rows):
    OUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="hoodie", help="Product key from product_catalog_plan.json. Default: hoodie")
    ap.add_argument("--create", action="store_true", help="Actually create the unpublished My Product")
    ap.add_argument("--placement", help="Override Printful placement")
    ap.add_argument("--technique", help="Override Printful technique")
    ap.add_argument("--artwork-url", default=DEFAULT_ARTWORK_URL, help="Public placeholder artwork URL")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    plan = load_json(PLAN_PATH)
    queue = load_json(QUEUE_PATH)

    spec = next((x for x in plan.get("products", []) if x.get("key") == args.only), None)
    item = next((x for x in queue if x.get("key") == args.only), None)
    if not spec or not item:
        raise SystemExit(f"Could not find product key '{args.only}' in plan + Stage 3 queue.")
    if item.get("fulfillment") != "printful":
        raise SystemExit(f"'{args.only}' is not a Printful-managed product.")
    if not item.get("catalog_product_id"):
        raise SystemExit(f"'{args.only}' has no locked catalog_product_id.")

    catalog_id = item["catalog_product_id"]
    product = get_catalog_product(token, catalog_id)
    placement, technique = choose_placement_and_technique(
        product,
        spec.get("technique_preference", []),
        args.placement,
        args.technique,
    )

    external_id = f"wedgeiq-{slug(args.only)}-direct-v1"
    payload = {
        "source": "catalog",
        "catalog_product_id": catalog_id,
        "name": item.get("display_name") or spec.get("display_name") or args.only,
        "external_id": external_id,
        "product_options": [],
        "placements": [
            {
                "placement": placement,
                "technique": technique,
                "layers": [
                    {
                        "type": "file",
                        "url": args.artwork_url,
                    }
                ],
            }
        ],
    }

    print(f"Product key:      {args.only}")
    print(f"Catalog product:  {catalog_id} | {product.get('name')}")
    print(f"Technique:        {technique}")
    print(f"Placement:        {placement}")
    print(f"External ID:      {external_id}")
    print(f"Artwork:          placeholder/manual-final")
    print("\nPOST payload:")
    print(json.dumps(payload, indent=2))

    if not args.create:
        print("\nDRY RUN ONLY — nothing was created.")
        print(f"To create this ONE pilot product, run:\n  python3 scripts/stage5_direct_my_product_create.py --only {args.only} --create")
        return

    print("\nCreating unpublished My Product through Printful v2...")
    response = request_json("POST", "/v2/products", token, store_id, payload)
    data = response.get("data")

    result_row = {
        "key": args.only,
        "catalog_product_id": catalog_id,
        "catalog_name": product.get("name"),
        "external_id": external_id,
        "placement": placement,
        "technique": technique,
        "create_response": response,
    }

    if not isinstance(data, dict) or not data:
        result_row["status"] = "unexpected_empty_response"
        rows = existing_results()
        rows.append(result_row)
        save_results(rows)
        print("Printful returned HTTP success but no product object in data.")
        print(f"Saved raw response to {OUT_PATH}")
        raise SystemExit(2)

    product_id = data.get("id")
    result_row["product_id"] = product_id
    result_row["status"] = "created"
    print(f"Created My Product ID: {product_id}")

    if product_id:
        try:
            detail = request_json("GET", f"/v2/products/{product_id}", token, store_id)
            result_row["product_detail"] = detail
        except Exception as e:
            result_row["detail_error"] = str(e)

        try:
            variants = request_json("GET", f"/v2/products/{product_id}/variants?limit=100", token, store_id)
            result_row["variants"] = variants
            variant_count = len(variants.get("data", []) or [])
            print(f"Returned My Product variants: {variant_count}")
        except Exception as e:
            result_row["variants_error"] = str(e)

    rows = [r for r in existing_results() if r.get("key") != args.only]
    rows.append(result_row)
    save_results(rows)
    print(f"Saved result to {OUT_PATH}")
    print("\nSTOP HERE for the pilot. Open Printful and confirm the hoodie/product exists and looks editable.")
    print("Do not bulk-create the remaining catalog until this pilot is visually confirmed.")


if __name__ == "__main__":
    main()
