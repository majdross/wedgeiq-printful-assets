#!/usr/bin/env python3
"""Stage 2B: duplicate the approved WedgeIQ NL3600 white DTF master template.

This script uses Printful's mature Product Templates API.

Requires:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Default mode is DRY RUN. Add --create to actually duplicate the master.

Current master template:
  106433451 - WedgeIQ MASTER - NL3600 White DTG
  (Printful technique is actually DTF.)

The duplicate endpoint preserves the product blank, selected color/sizes,
placements, and existing artwork. After duplication, open each copy in
Printful Design Maker and replace only the front artwork as needed.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.printful.com"
MASTER_TEMPLATE_ID = 106433451

TARGETS = [
    {"name": "WedgeIQ FLIGHT IT - NL3600 White DTF", "external_id": "wedgeiq-flight-it-nl3600-white-dtf-v1"},
    {"name": "WedgeIQ SPIN IT - NL3600 White DTF", "external_id": "wedgeiq-spin-it-nl3600-white-dtf-v1"},
    {"name": "WedgeIQ COMPRESS IT - NL3600 White DTF", "external_id": "wedgeiq-compress-it-nl3600-white-dtf-v1"},
    {"name": "WedgeIQ FLOP IT - NL3600 White DTF", "external_id": "wedgeiq-flop-it-nl3600-white-dtf-v1"},
    {"name": "WedgeIQ STICK IT - NL3600 White DTF", "external_id": "wedgeiq-stick-it-nl3600-white-dtf-v1"},
]


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
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise


def list_templates(token, store_id):
    return request_json("GET", "/product-templates?limit=100", token, store_id)


def existing_external_ids(doc):
    items = doc.get("result", {}).get("items", [])
    return {str(i.get("external_product_id")) for i in items if i.get("external_product_id")}


def duplicate_template(token, store_id, external_id):
    return request_json(
        "POST",
        f"/product-templates/{MASTER_TEMPLATE_ID}/duplicate",
        token,
        store_id,
        {"external_product_id": external_id},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="Actually duplicate the master template")
    ap.add_argument("--only", choices=["flight", "spin", "compress", "flop", "stick"], help="Create only one target")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    targets = TARGETS
    if args.only:
        needle = args.only.upper()
        targets = [t for t in TARGETS if needle in t["name"].upper()]

    templates = list_templates(token, store_id)
    existing = existing_external_ids(templates)

    print(f"Master template ID: {MASTER_TEMPLATE_ID}")
    print("Planned duplicates:")
    for t in targets:
        state = "SKIP - already exists" if t["external_id"] in existing else "READY"
        print(f"  {state}: {t['name']} | external_id={t['external_id']}")

    if not args.create:
        print("\nDRY RUN ONLY. To create one FLIGHT IT production copy first, run:")
        print("  python3 scripts/stage2_duplicate_master_templates.py --create --only flight")
        return

    results = []
    for t in targets:
        if t["external_id"] in existing:
            results.append({"target": t, "status": "skipped_existing"})
            continue

        print(f"\nDuplicating master for {t['name']}...")
        result = duplicate_template(token, store_id, t["external_id"])
        item = result.get("result", {})
        new_id = item.get("id")
        title = item.get("title")
        print(f"  Created template id={new_id} title={title}")
        print("  Note: Printful may assign a generic copy title; rename in dashboard if needed.")
        results.append({"target": t, "status": "created", "response": result})

    with open("stage2_duplicate_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\nWrote stage2_duplicate_results.json")
    print("Next: open each duplicate in Printful Design Maker and swap ONLY the front artwork.")
    print("Keep the white NL3600 blank, sizes, DTF placements, and small upper-back WedgeIQ treatment from the master.")
    print("Do not use STICK IT for production until the actual source artwork is corrected from legacy STIFF IT.")


if __name__ == "__main__":
    main()
