#!/usr/bin/env python3
"""Stage 5B: create a new Printful Product Template via the mature legacy swap-product API.

Why this exists:
- The account can read Product Templates through v2.
- POST /v2/product-templates currently returns 404 for this account/environment.
- Printful's mature Product Templates API exposes:
    POST /product-templates/{template_id}/swap-product
  which creates a NEW Product Template using a different catalog product.

This version uses the dedicated WedgeIQ DTG source template:
  106482179

The legacy swap endpoint requires the source Product Template to use DTG.
Default behavior is dry-run. Test ONE hoodie first and visually confirm the
result in Printful > Product templates before running additional targets.

Requires:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Examples:
  python3 scripts/stage5b_legacy_product_template_swap.py --only hoodie
  python3 scripts/stage5b_legacy_product_template_swap.py --only hoodie --create
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.printful.com"
SOURCE_TEMPLATE_ID = 106482179
OUT_PATH = Path("stage5b_legacy_swap_results.json")

TARGETS = {
    "hoodie": {
        "catalog_product_id": 380,
        "name": "WedgeIQ MASTER - Cotton Heritage M2580",
        "external_id": "wedgeiq-master-hoodie-m2580-legacy-v2",
    },
    "golf_polo": {
        "catalog_product_id": 767,
        "name": "WedgeIQ MASTER - Adidas A430 Polo",
        "external_id": "wedgeiq-master-adidas-a430-legacy-v2",
    },
    "quarter_zip_performance": {
        "catalog_product_id": 903,
        "name": "WedgeIQ MASTER - Sport-Tek ST357 Quarter Zip",
        "external_id": "wedgeiq-master-sporttek-st357-legacy-v2",
    },
    "quarter_zip_premium": {
        "catalog_product_id": 1473,
        "name": "WedgeIQ MASTER - Lane Seven LS14014 Quarter Zip",
        "external_id": "wedgeiq-master-laneseven-ls14014-legacy-v2",
    },
    "crewneck": {
        "catalog_product_id": 839,
        "name": "WedgeIQ MASTER - Comfort Colors 1566 Crewneck",
        "external_id": "wedgeiq-master-comfortcolors-1566-legacy-v2",
    },
    "outerwear": {
        "catalog_product_id": 790,
        "name": "WedgeIQ MASTER - Columbia Ascender 212483",
        "external_id": "wedgeiq-master-columbia-ascender-legacy-v2",
    },
    "golf_towel": {
        "catalog_product_id": 1423,
        "name": "WedgeIQ MASTER - Golf Towel",
        "external_id": "wedgeiq-master-golf-towel-legacy-v2",
    },
    "duffle": {
        "catalog_product_id": 465,
        "name": "WedgeIQ MASTER - AOP Duffle Bag",
        "external_id": "wedgeiq-master-aop-duffle-legacy-v2",
    },
}


def request_json(method, path, token, store_id, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-PF-Store-Id": str(store_id),
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return {
            "_http_error": True,
            "status": e.code,
            "body": body,
        }


def get_source(token, store_id):
    return request_json(
        "GET",
        f"/product-templates/{SOURCE_TEMPLATE_ID}",
        token,
        store_id,
    )


def source_is_dtg(source):
    techniques = {
        str(p.get("technique_key") or "").upper()
        for p in source.get("placements", []) or []
    }
    return "DTG" in techniques


def swap_product(token, store_id, target):
    payload = {
        "product_id": target["catalog_product_id"],
        "external_product_id": target["external_id"],
    }
    response = request_json(
        "POST",
        f"/product-templates/{SOURCE_TEMPLATE_ID}/swap-product",
        token,
        store_id,
        payload,
    )
    return payload, response


def save_result(row):
    rows = []
    if OUT_PATH.exists():
        try:
            rows = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
    rows = [r for r in rows if r.get("key") != row.get("key")]
    rows.append(row)
    OUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="hoodie", choices=sorted(TARGETS))
    ap.add_argument("--create", action="store_true")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    target = TARGETS[args.only]
    source_doc = get_source(token, store_id)
    if source_doc.get("_http_error"):
        raise SystemExit(f"Could not load source Product Template {SOURCE_TEMPLATE_ID}.")
    source = source_doc.get("result", {}) if isinstance(source_doc, dict) else {}

    print("WedgeIQ DTG Product Template swap pilot")
    print("----------------------------------------")
    print(f"Source template ID:      {SOURCE_TEMPLATE_ID}")
    print(f"Source title:            {source.get('title')}")
    print(f"Source catalog product:  {source.get('product_id')}")
    print("Source placements:")
    for p in source.get("placements", []) or []:
        print(f"  - {p.get('placement')} | technique={p.get('technique_key')}")

    if not source_is_dtg(source):
        raise SystemExit(
            "STOPPED: source template does not report a DTG placement. "
            "The legacy swap endpoint requires a DTG source."
        )

    print("Source validation:       DTG CONFIRMED")
    print(f"\nTarget key:              {args.only}")
    print(f"Target catalog product:  {target['catalog_product_id']}")
    print(f"External product ID:     {target['external_id']}")

    payload = {
        "product_id": target["catalog_product_id"],
        "external_product_id": target["external_id"],
    }
    print("\nPlanned POST:")
    print(f"  /product-templates/{SOURCE_TEMPLATE_ID}/swap-product")
    print(json.dumps(payload, indent=2))

    if not args.create:
        print("\nDRY RUN ONLY — nothing created.")
        print("If DTG is confirmed above, run the controlled hoodie test:")
        print(f"  python3 scripts/stage5b_legacy_product_template_swap.py --only {args.only} --create")
        return

    print("\nAttempting legacy Product Template swap...")
    sent, response = swap_product(token, store_id, target)
    row = {
        "key": args.only,
        "source_template_id": SOURCE_TEMPLATE_ID,
        "target": target,
        "payload": sent,
        "response": response,
    }

    if response.get("_http_error"):
        row["status"] = "failed"
        save_result(row)
        print(f"Swap failed with HTTP {response.get('status')}.")
        print(f"Saved response to {OUT_PATH}")
        raise SystemExit(2)

    result = response.get("result", {}) or {}
    new_id = result.get("id")
    row["new_template_id"] = new_id
    row["status"] = "created" if new_id else "unexpected_response"
    save_result(row)

    print(f"Saved response to {OUT_PATH}")
    if not new_id:
        print("No new Product Template ID returned. Stop here.")
        raise SystemExit(2)

    print(f"SUCCESS — new Product Template ID: {new_id}")
    print(f"Returned title: {result.get('title')}")
    print(f"Returned product_id: {result.get('product_id')}")
    print("\nSTOP HERE. Open Printful > Product templates and visually verify:")
    print("  1. the new hoodie template exists")
    print("  2. the blank is Cotton Heritage M2580")
    print("  3. placements/artwork transferred acceptably")
    print("Do not run other products until this pilot is confirmed.")


if __name__ == "__main__":
    main()
