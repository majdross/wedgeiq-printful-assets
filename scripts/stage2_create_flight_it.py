#!/usr/bin/env python3
"""Stage 2: discover the Next Level 3600 catalog product and create one unpublished WedgeIQ FLIGHT IT My Product in Printful.

Default mode is DISCOVERY ONLY. Use --create only after reviewing the printed catalog product and variants.

Requires environment variables:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

This intentionally creates an unpublished My Product first. It does not publish to Shopify.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.printful.com"
RAW_BASE = "https://raw.githubusercontent.com/majdross/wedgeiq-printful-assets/main"
ARTWORK = "01_PRINTFUL_UPLOAD/TEE_DTG/FLIGHT_IT_NAVY_3600px.png"
PRODUCT_NAME = "WedgeIQ FLIGHT IT Tee | Next Level 3600"
EXTERNAL_ID = "wedgeiq-flight-it-nl3600-v1"


def request_json(method, path, token, store_id=None, payload=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if store_id:
        headers["X-PF-Store-Id"] = str(store_id)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise


def find_next_level_3600(token):
    offset = 0
    matches = []
    while True:
        path = f"/v2/catalog-products?limit=100&offset={offset}&selling_region_name=north_america"
        doc = request_json("GET", path, token)
        data = doc.get("data", [])
        for p in data:
            hay = " ".join(str(p.get(k, "")) for k in ("name", "brand", "model")).lower()
            if "next level" in hay and "3600" in hay:
                matches.append(p)
        paging = doc.get("paging", {})
        total = paging.get("total", 0)
        offset += len(data)
        if not data or offset >= total:
            break
    return matches


def get_variants(token, product_id):
    offset = 0
    all_variants = []
    while True:
        path = f"/v2/catalog-products/{product_id}/catalog-variants?limit=100&offset={offset}"
        doc = request_json("GET", path, token)
        data = doc.get("data", [])
        all_variants.extend(data)
        paging = doc.get("paging", {})
        total = paging.get("total", 0)
        offset += len(data)
        if not data or offset >= total:
            break
    return all_variants


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="Create the unpublished FLIGHT IT My Product after discovery")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    matches = find_next_level_3600(token)
    if not matches:
        raise SystemExit("Could not find a Printful catalog product matching Next Level 3600.")

    print("\nMatching catalog products:")
    for p in matches:
        print(f"  id={p.get('id')} | {p.get('name')} | brand={p.get('brand')} | model={p.get('model')}")

    if len(matches) != 1:
        print("\nMore than one match found. No product will be created. Review the IDs and refine the script.")
        return

    product = matches[0]
    product_id = product["id"]
    variants = get_variants(token, product_id)

    preferred_sizes = {"S", "M", "L", "XL", "2XL", "XXL"}
    white = [v for v in variants if str(v.get("color", "")).lower() == "white" and str(v.get("size", "")).upper() in preferred_sizes]

    print(f"\nSelected catalog product: {product_id} — {product.get('name')}")
    print("White launch variants found:")
    for v in white:
        print(f"  variant_id={v.get('id')} | {v.get('color')} | {v.get('size')}")

    discovery = {
        "catalog_product": product,
        "white_launch_variants": white,
        "artwork_url": f"{RAW_BASE}/{ARTWORK}",
        "planned_name": PRODUCT_NAME,
        "planned_external_id": EXTERNAL_ID,
    }
    with open("stage2_flight_it_discovery.json", "w", encoding="utf-8") as f:
        json.dump(discovery, f, indent=2)
    print("\nWrote stage2_flight_it_discovery.json")

    if not args.create:
        print("\nDISCOVERY ONLY. If the catalog match/variants look correct, run:")
        print("  python3 scripts/stage2_create_flight_it.py --create")
        return

    artwork_url = f"{RAW_BASE}/{urllib.parse.quote(ARTWORK, safe='/._-')}"
    payload = {
        "product_options": [],
        "placements": [
            {
                "placement": "front",
                "technique": "dtg",
                "print_area_type": "simple",
                "layers": [
                    {
                        "type": "file",
                        "url": artwork_url,
                        "position": {}
                    }
                ],
                "placement_options": []
            }
        ],
        "external_id": EXTERNAL_ID,
        "source": "catalog",
        "catalog_product_id": product_id,
        "name": PRODUCT_NAME
    }

    print("\nCreating unpublished Printful My Product...")
    result = request_json("POST", "/v2/products", token, store_id, payload)
    with open("stage2_flight_it_product.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    data = result.get("data", {})
    print(f"Created product id={data.get('id')} name={data.get('name')}")
    print("Wrote stage2_flight_it_product.json")
    print("This product is UNPUBLISHED; it has not been pushed to Shopify.")


if __name__ == "__main__":
    main()
