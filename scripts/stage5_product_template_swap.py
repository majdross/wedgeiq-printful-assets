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
  - falls back to the legacy compatible-products endpoint if v2 returns 404
  - tests the requested target against that list
  - does NOT create anything unless --create is supplied
  - refuses an incompatible/unknown target unless --force is supplied

Examples:
  python3 scripts/stage5_product_template_swap.py --only hoodie
  python3 scripts/stage5_product_template_swap.py --only hoodie --create
  python3 scripts/stage5_product_template_swap.py --only hoodie --create --force

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
import urllib.request
from pathlib import Path

API = "https://api.printful.com"
SOURCE_TEMPLATE_ID = 106433451
OUT_PATH = Path("stage5_product_template_swap_results.json")

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


def request_json(method, path, token, store_id=None, payload=None, allow_404=False):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
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
        if allow_404 and e.code == 404:
            return {"_http_404": True, "_raw": body}
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
    """Try v2 first. If Printful returns 404, fall back to legacy endpoint."""
    v2_path = f"/v2/product-templates/{SOURCE_TEMPLATE_ID}/compatible-products?limit=100&offset=0"
    doc = request_json("GET", v2_path, token, store_id, allow_404=True)

    if not doc.get("_http_404"):
        return {
            "endpoint": "v2",
            "supported": True,
            "items": doc.get("data", []) or [],
            "raw": doc,
        }

    print("v2 compatible-products returned 404; trying legacy Product Templates endpoint...")
    legacy_path = f"/product-templates/{SOURCE_TEMPLATE_ID}/compatible-products?limit=100&offset=0"
    legacy = request_json("GET", legacy_path, token, store_id, allow_404=True)

    if legacy.get("_http_404"):
        return {
            "endpoint": "none",
            "supported": False,
            "items": [],
            "raw": {"v2": doc, "legacy": legacy},
        }

    return {
        "endpoint": "legacy",
        "supported": True,
        "items": legacy.get("result", []) or [],
        "raw": legacy,
    }


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
    ap.add_argument("--force", action="store_true", help="Attempt transfer even if compatibility is NO or cannot be checked")
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
    compat = get_compatible_products(token, store_id)
    compatible = compat["items"]
    match = find_target(compatible, target["catalog_product_id"])

    print(f"Compatibility endpoint:         {compat['endpoint']}")
    print(f"Compatibility check supported:  {'YES' if compat['supported'] else 'NO'}")
    print(f"Compatible products returned:   {len(compatible)}")
    if compat["supported"]:
        print(f"Target compatible:              {'YES' if match else 'NO'}")
    else:
        print("Target compatible:              UNKNOWN (endpoint unavailable)")
    if match:
        print(f"Matched product:                {match.get('name') or match.get('title')} | id={product_id(match)}")

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
        "compatibility_endpoint": compat["endpoint"],
        "compatibility_supported": compat["supported"],
        "compatible": bool(match) if compat["supported"] else None,
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
        elif not compat["supported"]:
            print("Printful would not expose either compatible-products endpoint for this template/account.")
            print("The v2 create-from-template operation is still documented, but compatibility cannot be pre-validated.")
            print("For ONE intentional pilot only, use:")
            print(f"  python3 scripts/stage5_product_template_swap.py --only {args.only} --create --force")
        else:
            print("Target is NOT in Printful's compatible-products list.")
            print("For one intentional experiment only, add --force.")
        return

    if not match and not args.force:
        result["status"] = "blocked_unverified_or_incompatible"
        save_result(result)
        raise SystemExit(
            "STOPPED: target is not confirmed compatible. Nothing was created. "
            "Use --force only for a single intentional pilot."
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
