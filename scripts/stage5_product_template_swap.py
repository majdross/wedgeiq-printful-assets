#!/usr/bin/env python3
"""Stage 5: create WedgeIQ items in Printful's Product Templates area.

This uses Printful Product Templates v2, NOT /v2/products.

Printful does not allow creating a brand-new Product Template from scratch by API.
It DOES allow creating one from an existing Product Template and optionally
swapping the underlying Catalog Product.

Pilot source master:
  106433451 - existing WedgeIQ NL3600 Product Template

Default behavior:
  - DRY RUN
  - checks the source template
  - checks Printful's compatible-products list
  - tests the requested target against that list
  - does NOT create anything unless --create is supplied
  - refuses an incompatible target unless --force is supplied

Examples:
  python3 scripts/stage5_product_template_swap.py --only hoodie
  python3 scripts/stage5_product_template_swap.py --only hoodie --create

Requires:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Output:
  stage5_product_template_swap_results.json
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.printful.com"
SOURCE_TEMPLATE_ID = 106433451
PLAN_PATH = Path("product_catalog_plan.json")
OUT_PATH = Path("stage5_product_template_swap_results.json")

# Locked target products from the approved WedgeIQ catalog plan.
TARGETS = {
    "hoodie": {
        "catalog_product_id": 380,
        "name": "WedgeIQ MASTER - Cotton Heritage M2580",
        "external_id": "wedgeiq-master-hoodie-m2580-v1",
    },
    "golf_polo": {
        "catalog_product_id": 767,
        "name": "WedgeIQ MASTER - Adidas A430 Polo",
        "external_id": "wedgeiq-master-adidas-a430-v1",
    },
    "quarter_zip_performance": {
        "catalog_product_id": 903,
        "name": "WedgeIQ MASTER - Sport-Tek ST357 Quarter Zip",
        "external_id": "wedgeiq-master-sporttek-st357-v1",
    },
    "quarter_zip_premium": {
        "catalog_product_id": 1473,
        "name": "WedgeIQ MASTER - Lane Seven LS14014 Quarter Zip",
        "external_id": "wedgeiq-master-laneseven-ls14014-v1",
    },
    "crewneck": {
        "catalog_product_id": 839,
        "name": "WedgeIQ MASTER - Comfort Colors 1566 Crewneck",
        "external_id": "wedgeiq-master-comfortcolors-1566-v1",
    },
    "outerwear": {
        "catalog_product_id": 790,
        "name": "WedgeIQ MASTER - Columbia Ascender 212483",
        "external_id": "wedgeiq-master-columbia-ascender-v1",
    },
    "golf_towel": {
        "catalog_product_id": 1423,
        "name": "WedgeIQ MASTER - Golf Towel",
        "external_id": "wedgeiq-master-golf-towel-v1",
    },
    "duffle": {
        "catalog_product_id": 465,
        "name": "WedgeIQ MASTER - AOP Duffle Bag",
        "external_id": "wedgeiq-master-aop-duffle-v1",
    },
}


def request_json(method, path, token, store_id=None, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # Product Templates are account/environment resources, but keeping the store
    # header is safe for the account-level token setup already used by WedgeIQ.
    if store_id:
        headers["X-PF-Store-Id"] = str(store_id)

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise


def get_source_template(token, store_id):
    return request_json(
        "GET",
        f"/v2/product-templates/{SOURCE_TEMPLATE_ID}",
        token,
        store_id,
    )


def get_compatible_products(token, store_id):
    # Follow pagination in case Printful returns more than one page.
    items = []
    offset = 0
    limit = 100
    while True:
        doc = request_json(
            "GET",
            f"/v2/product-templates/{SOURCE_TEMPLATE_ID}/compatible-products?limit={limit}&offset={offset}",
            token,
            store_id,
        )
        page = doc.get("data", []) or []
        items.extend(page)
        paging = doc.get("paging", {}) or {}
        total = paging.get("total")
        if not page:
            break
        offset += len(page)
        if total is not None and offset >= total:
            break
        if len(page) < limit:
            break
    return items


def product_id(item):
    return item.get("id") or item.get("catalog_product_id")


def find_target(items, target_id):
    for item in items:
        try:
            if int(product_id(item)) == int(target_id):
                return item
        except (TypeError, ValueError):
            pass
    return None


def create_template(token, store_id, target):
    payload = {
        "source": "product_template",
        "product_template_id": SOURCE_TEMPLATE_ID,
        "catalog_product_id": target["catalog_product_id"],
        "name": target["name"],
        "external_id": target["external_id"],
    }
    return payload, request_json(
        "POST",
        "/v2/product-templates",
        token,
        store_id,
        payload,
    )


def save_result(result):
    rows = []
    if OUT_PATH.exists():
        try:
            rows = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
    rows = [r for r in rows if r.get("key") != result.get("key")]
    rows.append(result)
    OUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="hoodie", choices=sorted(TARGETS), help="Target product key")
    ap.add_argument("--create", action="store_true", help="Actually create the Product Template")
    ap.add_argument("--force", action="store_true", help="Allow transfer even if target is not in Printful compatible-products list")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    target = TARGETS[args.only]

    print("WedgeIQ Product Template swap pilot")
    print("-----------------------------------")
    print(f"Source Product Template: {SOURCE_TEMPLATE_ID}")
    print(f"Target key:              {args.only}")
    print(f"Target catalog product:  {target['catalog_product_id']}")
    print(f"Target template name:    {target['name']}")
    print(f"External ID:             {target['external_id']}")

    source_doc = get_source_template(token, store_id)
    source = source_doc.get("data", {}) or {}
    print(f"\nSource name:             {source.get('name')}")
    print(f"Source catalog product:  {source.get('catalog_product_id')}")
    placements = source.get("placements", []) or []
    if placements:
        print("Source placements:")
        for p in placements:
            print(f"  - {p.get('placement')} | technique={p.get('technique')} | status={p.get('status')}")

    print("\nChecking Printful compatible products...")
    compatible = get_compatible_products(token, store_id)
    match = find_target(compatible, target["catalog_product_id"])
    print(f"Compatible products returned: {len(compatible)}")
    print(f"Target compatible:            {'YES' if match else 'NO'}")
    if match:
        print(f"Matched product:              {match.get('name')} | id={product_id(match)}")

    payload = {
        "source": "product_template",
        "product_template_id": SOURCE_TEMPLATE_ID,
        "catalog_product_id": target["catalog_product_id"],
        "name": target["name"],
        "external_id": target["external_id"],
    }
    print("\nPlanned POST /v2/product-templates payload:")
    print(json.dumps(payload, indent=2))

    result = {
        "key": args.only,
        "source_template_id": SOURCE_TEMPLATE_ID,
        "target": target,
        "compatible": bool(match),
        "compatible_match": match,
        "payload": payload,
    }

    if not args.create:
        result["status"] = "dry_run"
        save_result(result)
        print("\nDRY RUN ONLY — nothing created.")
        if match:
            print("Target is compatible. To create it in Product Templates:")
            print(f"  python3 scripts/stage5_product_template_swap.py --only {args.only} --create")
        else:
            print("Target is NOT in Printful's compatible-products list.")
            print("Do not use --force unless you intentionally want to test a potentially incomplete design transfer.")
        return

    if not match and not args.force:
        result["status"] = "blocked_incompatible"
        save_result(result)
        raise SystemExit(
            "STOPPED: target is not in Printful's compatible-products list. "
            "Nothing was created. Use --force only for an intentional experiment."
        )

    print("\nCreating Product Template in Printful...")
    payload, response = create_template(token, store_id, target)
    result["response"] = response
    data = response.get("data", {}) if isinstance(response, dict) else {}
    new_id = data.get("id") if isinstance(data, dict) else None
    result["new_template_id"] = new_id
    result["status"] = "created" if new_id else "unexpected_response"
    save_result(result)

    print(f"Printful response saved to {OUT_PATH}")
    if new_id:
        print(f"SUCCESS — created Product Template ID: {new_id}")
        print("Open Printful > Product templates and confirm the new template is visible/editable.")
        print("Do not bulk-run the remaining products until this one pilot is visually confirmed.")
    else:
        print("Printful did not return a Product Template ID. Inspect the saved raw response before proceeding.")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
