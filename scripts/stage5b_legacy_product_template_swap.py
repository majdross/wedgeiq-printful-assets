#!/usr/bin/env python3
"""Stage 5B: automate WedgeIQ Product Template creation via Printful's legacy DTG swap API.

Proven path:
  POST /product-templates/{template_id}/swap-product

Dedicated DTG source Product Template:
  106482179 - WedgeIQ Hoodie Flight It

The legacy swap endpoint requires a DTG source. This script validates the source,
checks Printful's compatible-products endpoint, and can create every compatible
recommended WedgeIQ Product Template while skipping products already registered
as masters.

Default behavior is dry-run.

Examples:
  python3 scripts/stage5b_legacy_product_template_swap.py --only golf_polo
  python3 scripts/stage5b_legacy_product_template_swap.py --only golf_polo --create
  python3 scripts/stage5b_legacy_product_template_swap.py --check-all
  python3 scripts/stage5b_legacy_product_template_swap.py --create-all-compatible

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
SOURCE_TEMPLATE_ID = 106482179
OUT_PATH = Path("stage5b_legacy_swap_results.json")
REGISTRY_PATH = Path("product_master_registry.json")

TARGETS = {
    "hoodie": {
        "catalog_product_id": 380,
        "name": "WedgeIQ MASTER - Cotton Heritage M2580",
        "external_id": "wedgeiq-master-hoodie-m2580-legacy-v3",
    },
    "golf_polo": {
        "catalog_product_id": 767,
        "name": "WedgeIQ MASTER - Adidas A430 Polo",
        "external_id": "wedgeiq-master-adidas-a430-legacy-v3",
    },
    "quarter_zip_performance": {
        "catalog_product_id": 903,
        "name": "WedgeIQ MASTER - Sport-Tek ST357 Quarter Zip",
        "external_id": "wedgeiq-master-sporttek-st357-legacy-v3",
    },
    "quarter_zip_premium": {
        "catalog_product_id": 1473,
        "name": "WedgeIQ MASTER - Lane Seven LS14014 Quarter Zip",
        "external_id": "wedgeiq-master-laneseven-ls14014-legacy-v3",
    },
    "crewneck": {
        "catalog_product_id": 839,
        "name": "WedgeIQ MASTER - Comfort Colors 1566 Crewneck",
        "external_id": "wedgeiq-master-comfortcolors-1566-legacy-v3",
    },
    "outerwear": {
        "catalog_product_id": 790,
        "name": "WedgeIQ MASTER - Columbia Ascender 212483",
        "external_id": "wedgeiq-master-columbia-ascender-legacy-v3",
    },
    "golf_towel": {
        "catalog_product_id": 1423,
        "name": "WedgeIQ MASTER - Golf Towel",
        "external_id": "wedgeiq-master-golf-towel-legacy-v3",
    },
    "duffle": {
        "catalog_product_id": 465,
        "name": "WedgeIQ MASTER - AOP Duffle Bag",
        "external_id": "wedgeiq-master-aop-duffle-legacy-v3",
    },
}


def request_json(method, path, token, store_id, payload=None, allow_404=False):
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
        if allow_404 and e.code == 404:
            return {"_http_404": True, "status": 404, "body": body}
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return {"_http_error": True, "status": e.code, "body": body}


def get_source(token, store_id):
    return request_json("GET", f"/product-templates/{SOURCE_TEMPLATE_ID}", token, store_id)


def source_is_dtg(source):
    techniques = {
        str(p.get("technique_key") or "").upper()
        for p in source.get("placements", []) or []
    }
    return "DTG" in techniques


def get_compatible_products(token, store_id):
    path = f"/product-templates/{SOURCE_TEMPLATE_ID}/compatible-products?limit=100&offset=0"
    doc = request_json("GET", path, token, store_id, allow_404=True)
    if doc.get("_http_404") or doc.get("_http_error"):
        return {"supported": False, "items": [], "raw": doc}
    return {"supported": True, "items": doc.get("result", []) or [], "raw": doc}


def product_id(item):
    return item.get("id") or item.get("catalog_product_id") or item.get("product_id")


def find_target(items, target_id):
    for item in items:
        try:
            if int(product_id(item)) == int(target_id):
                return item
        except (TypeError, ValueError):
            pass
    return None


def load_registered_masters():
    if not REGISTRY_PATH.exists():
        return {}
    try:
        doc = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return doc.get("masters", {}) if isinstance(doc, dict) else {}
    except Exception:
        return {}


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


def load_results():
    if not OUT_PATH.exists():
        return []
    try:
        rows = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def save_result(row):
    rows = load_results()
    rows = [r for r in rows if r.get("key") != row.get("key")]
    rows.append(row)
    OUT_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def already_created_from_results(key):
    for row in load_results():
        if row.get("key") == key and row.get("status") == "created" and row.get("new_template_id"):
            return row.get("new_template_id")
    return None


def display_source(source):
    print("WedgeIQ DTG Product Template automation")
    print("---------------------------------------")
    print(f"Source template ID:      {SOURCE_TEMPLATE_ID}")
    print(f"Source title:            {source.get('title')}")
    print(f"Source catalog product:  {source.get('product_id')}")
    print("Source placements:")
    for p in source.get("placements", []) or []:
        print(f"  - {p.get('placement')} | technique={p.get('technique_key')}")
    print("Source validation:       DTG CONFIRMED")


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--only", choices=sorted(TARGETS), help="Work with one recommended target")
    mode.add_argument("--check-all", action="store_true", help="Check all recommended targets; create nothing")
    mode.add_argument(
        "--create-all-compatible",
        action="store_true",
        help="Create every compatible recommended target that is not already registered/created",
    )
    ap.add_argument("--create", action="store_true", help="Create the --only target")
    args = ap.parse_args()

    if args.create and not args.only:
        raise SystemExit("--create must be used with --only.")

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")

    source_doc = get_source(token, store_id)
    if source_doc.get("_http_error"):
        raise SystemExit(f"Could not load source Product Template {SOURCE_TEMPLATE_ID}.")
    source = source_doc.get("result", {}) if isinstance(source_doc, dict) else {}
    if not source_is_dtg(source):
        raise SystemExit("STOPPED: source template is not DTG. Nothing created.")

    display_source(source)
    print("\nChecking Printful compatible products...")
    compat = get_compatible_products(token, store_id)
    if not compat["supported"]:
        raise SystemExit("STOPPED: Printful compatible-products endpoint is unavailable. Nothing created.")

    compatible_items = compat["items"]
    print(f"Compatible products returned: {len(compatible_items)}")
    registered = load_registered_masters()

    keys = [args.only] if args.only else list(TARGETS.keys())
    create_all = args.create_all_compatible
    create_one = bool(args.only and args.create)

    print("\nRecommended target plan")
    print("-----------------------")
    plan = []
    for key in keys:
        target = TARGETS[key]
        match = find_target(compatible_items, target["catalog_product_id"])
        registered_id = (registered.get(key) or {}).get("template_id")
        previous_id = already_created_from_results(key)

        if registered_id:
            action = f"SKIP — registered master {registered_id}"
        elif previous_id:
            action = f"SKIP — already created {previous_id}"
        elif match:
            action = "CREATE" if (create_all or create_one) else "READY"
        else:
            action = "SKIP — incompatible"

        matched_name = ""
        if match:
            matched_name = match.get("name") or match.get("title") or ""

        print(
            f"{key:26} | product {target['catalog_product_id']:4} | "
            f"compatible={'YES' if match else 'NO ':3} | {action}"
        )
        if matched_name:
            print(f"  ↳ {matched_name}")

        plan.append((key, target, match, registered_id, previous_id))

    if not create_all and not create_one:
        print("\nDRY RUN ONLY — nothing created.")
        if args.check_all or not args.only:
            print("To create every compatible unregistered recommended product:")
            print("  python3 scripts/stage5b_legacy_product_template_swap.py --create-all-compatible")
        elif args.only:
            print(f"To create {args.only}:")
            print(f"  python3 scripts/stage5b_legacy_product_template_swap.py --only {args.only} --create")
        return

    print("\nCreating compatible Product Templates...")
    created = []
    skipped = []
    failed = []

    for key, target, match, registered_id, previous_id in plan:
        if registered_id:
            skipped.append((key, f"registered master {registered_id}"))
            continue
        if previous_id:
            skipped.append((key, f"already created {previous_id}"))
            continue
        if not match:
            skipped.append((key, "not compatible"))
            continue

        print(f"\n[{key}] swapping to catalog product {target['catalog_product_id']}...")
        sent, response = swap_product(token, store_id, target)
        row = {
            "key": key,
            "source_template_id": SOURCE_TEMPLATE_ID,
            "target": target,
            "compatible_match": match,
            "payload": sent,
            "response": response,
        }

        if response.get("_http_error"):
            row["status"] = "failed"
            save_result(row)
            failed.append((key, response.get("status"), response.get("body")))
            print(f"  FAILED HTTP {response.get('status')}")
            continue

        result = response.get("result", {}) or {}
        new_id = result.get("id")
        row["new_template_id"] = new_id
        row["status"] = "created" if new_id else "unexpected_response"
        save_result(row)

        if new_id:
            created.append((key, new_id, result.get("title"), result.get("product_id")))
            print(f"  SUCCESS — template {new_id} | {result.get('title')}")
        else:
            failed.append((key, "no_template_id", json.dumps(response)))
            print("  FAILED — no Product Template ID returned")

    print("\nAutomation summary")
    print("------------------")
    if created:
        print("Created:")
        for key, new_id, title, pid in created:
            print(f"  - {key}: template {new_id} | product {pid} | {title}")
    else:
        print("Created: none")

    if skipped:
        print("Skipped:")
        for key, reason in skipped:
            print(f"  - {key}: {reason}")

    if failed:
        print("Failed:")
        for key, status, _body in failed:
            print(f"  - {key}: {status}")

    print(f"\nDetailed responses saved to {OUT_PATH}")
    print("Open Printful > Product templates and review the created blanks before final artwork/technique cleanup.")

    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
