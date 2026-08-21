#!/usr/bin/env python3
"""Register a manually-created Printful Product Template as a WedgeIQ master.

Purpose:
Printful's swap-product automation cannot create every recommended product family.
For those families, create ONE master manually in Printful, then register its
Product Template ID here. The script validates the template through Printful's
legacy Product Templates API and updates product_master_registry.json locally.

Examples:
  python3 scripts/stage6_register_manual_master.py --key golf_polo --template-id 123456789
  python3 scripts/stage6_register_manual_master.py --key outerwear --template-id 123456789

Requires:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.printful.com"
REGISTRY = Path("product_master_registry.json")

EXPECTED = {
    "golf_polo": {"catalog_product_id": 767, "technique": "embroidery", "name": "Adidas A430"},
    "quarter_zip_performance": {"catalog_product_id": 903, "technique": "DTF", "name": "Sport-Tek ST357"},
    "quarter_zip_premium": {"catalog_product_id": 1473, "technique": "embroidery", "name": "Lane Seven LS14014"},
    "outerwear": {"catalog_product_id": 790, "technique": "embroidery", "name": "Columbia Ascender 212483"},
}


def request_json(path, token, store_id):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-PF-Store-Id": str(store_id),
    }
    req = urllib.request.Request(API + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Printful HTTP {e.code}: {body}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, choices=sorted(EXPECTED))
    ap.add_argument("--template-id", required=True, type=int)
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    expected = EXPECTED[args.key]
    doc = request_json(f"/product-templates/{args.template_id}", token, store_id)
    result = doc.get("result", {}) if isinstance(doc, dict) else {}

    title = result.get("title")
    product_id = result.get("product_id")
    placements = result.get("placements", []) or []
    techniques = sorted({str(p.get("technique_key") or "").upper() for p in placements if p.get("technique_key")})

    print("WedgeIQ manual master registration")
    print("----------------------------------")
    print(f"Key:                  {args.key}")
    print(f"Template ID:          {args.template_id}")
    print(f"Printful title:       {title}")
    print(f"Catalog product ID:   {product_id}")
    print(f"Expected product ID:  {expected['catalog_product_id']}")
    print(f"Techniques found:     {', '.join(techniques) if techniques else 'none'}")

    if int(product_id or 0) != int(expected["catalog_product_id"]):
        raise SystemExit("STOPPED: template catalog product does not match the recommended product for this key.")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = registry.setdefault("masters", {}).setdefault(args.key, {})
    entry.update({
        "catalog_product_id": expected["catalog_product_id"],
        "template_id": args.template_id,
        "status": "existing",
        "technique": expected["technique"],
        "artwork": "manual",
        "notes": f"Registered manual master: {title or expected['name']}",
    })
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    print("\nREGISTERED SUCCESSFULLY")
    print(f"Updated {REGISTRY}")
    print("Commit/push the registry after all launch masters are registered.")


if __name__ == "__main__":
    main()
