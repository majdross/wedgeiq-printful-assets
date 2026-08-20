#!/usr/bin/env python3
"""Build the WedgeIQ recommended Printful product queue.

What this DOES automate:
- Reads product_catalog_plan.json
- Pulls the current Printful Catalog v2
- Matches each recommended product by exact catalog ID, brand/model, or search terms
- Pulls variants for matched products
- Validates requested colors/sizes against what Printful currently offers
- Produces a ranked candidate list when the match is ambiguous
- Writes a clean build queue for manual template/artwork completion

What this intentionally DOES NOT automate:
- Artwork/logo placement
- Creating a brand-new Product Template from scratch (Printful API does not support that reliably)
- Publishing to Shopify

Requires:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Usage:
  python3 scripts/stage3_build_recommended_product_queue.py
  python3 scripts/stage3_build_recommended_product_queue.py --only quarter_zip_performance

Outputs:
  stage3_product_queue.json
  stage3_product_queue.csv
  stage3_product_candidates.json
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

API = "https://api.printful.com"
PLAN_PATH = Path("product_catalog_plan.json")


def request_json(path, token, store_id=None):
    headers = {"Authorization": f"Bearer {token}"}
    if store_id:
        headers["X-PF-Store-Id"] = str(store_id)
    req = urllib.request.Request(API + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        raise


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def get_all_catalog_products(token):
    products = []
    offset = 0
    limit = 100
    while True:
        doc = request_json(f"/v2/catalog-products?limit={limit}&offset={offset}&destination_country=US", token)
        data = doc.get("data", [])
        products.extend(data)
        paging = doc.get("paging", {})
        total = paging.get("total")
        if not data:
            break
        offset += len(data)
        if total is not None and offset >= total:
            break
    return products


def get_variants(token, product_id):
    variants = []
    offset = 0
    limit = 100
    while True:
        doc = request_json(f"/v2/catalog-products/{product_id}/catalog-variants?limit={limit}&offset={offset}&selling_region_name=north_america", token)
        data = doc.get("data", [])
        variants.extend(data)
        paging = doc.get("paging", {})
        total = paging.get("total")
        if not data:
            break
        offset += len(data)
        if total is not None and offset >= total:
            break
    return variants


def score_product(spec, product):
    name = normalize(product.get("name"))
    brand = normalize(product.get("brand"))
    model = normalize(product.get("model"))
    score = 0.0

    preferred_brand = normalize(spec.get("preferred_brand"))
    preferred_model = normalize(spec.get("preferred_model"))

    if preferred_brand and preferred_brand == brand:
        score += 35
    elif preferred_brand and preferred_brand in name:
        score += 25

    if preferred_model and preferred_model == model:
        score += 45
    elif preferred_model and preferred_model in name:
        score += 35

    for term in spec.get("search_terms", []):
        nt = normalize(term)
        if not nt:
            continue
        if nt in name:
            score += 30
        else:
            score += 20 * SequenceMatcher(None, nt, name).ratio()

    if product.get("is_discontinued"):
        score -= 100

    return round(score, 2)


def best_candidates(spec, products, count=5):
    exact_id = spec.get("catalog_product_id")
    if exact_id:
        exact = [p for p in products if p.get("id") == exact_id]
        if exact:
            return [{"score": 999.0, "product": exact[0]}]

    ranked = []
    for p in products:
        score = score_product(spec, p)
        if score > 0:
            ranked.append({"score": score, "product": p})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:count]


def variant_values(variant):
    # Printful v2 generally exposes color/size as properties, but names can vary.
    color = variant.get("color") or variant.get("color_name")
    size = variant.get("size") or variant.get("size_name")
    name = variant.get("name", "")

    if not color or not size:
        # Fallback for names such as "Product Name (Black / XL)".
        m = re.search(r"\(([^()/]+)\s*/\s*([^()]+)\)\s*$", name)
        if m:
            color = color or m.group(1).strip()
            size = size or m.group(2).strip()

    return color, size


def uniq_preserve(values):
    seen = set()
    out = []
    for v in values:
        if v is None:
            continue
        key = str(v).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(v).strip())
    return out


def choose_requested(requested, available):
    if not requested:
        return []
    lookup = {normalize(x): x for x in available}
    selected = []
    missing = []
    for item in requested:
        key = normalize(item)
        if key in lookup:
            selected.append(lookup[key])
            continue
        # soft match for variants like Navy vs True Navy / Heather Grey vs Athletic Heather
        matches = [x for x in available if key in normalize(x) or normalize(x) in key]
        if len(matches) == 1:
            selected.append(matches[0])
        else:
            missing.append(item)
    return uniq_preserve(selected), missing


def build_queue_item(spec, candidates, token):
    base = {
        "key": spec["key"],
        "display_name": spec["display_name"],
        "category": spec.get("category"),
        "priority": spec.get("priority"),
        "fulfillment": spec.get("fulfillment"),
        "automation_action": spec.get("automation_action"),
        "manual_artwork": True,
    }

    if spec.get("fulfillment") != "printful":
        base.update({
            "status": "external_manual",
            "note": spec.get("note", "Not managed through Printful."),
        })
        return base

    if not candidates:
        base.update({
            "status": "no_match",
            "action_required": "Review search terms or select a Printful catalog product manually."
        })
        return base

    winner = candidates[0]
    product = winner["product"]
    second_score = candidates[1]["score"] if len(candidates) > 1 else 0
    exact_id = spec.get("catalog_product_id") == product.get("id") if spec.get("catalog_product_id") else False
    exact_model = normalize(spec.get("preferred_model")) and normalize(spec.get("preferred_model")) == normalize(product.get("model"))
    strong_unique = winner["score"] >= 60 and (winner["score"] - second_score >= 15)
    auto_selected = bool(exact_id or exact_model or strong_unique)

    variants = get_variants(token, product["id"]) if auto_selected else []
    available_colors = []
    available_sizes = []
    variant_rows = []
    for v in variants:
        color, size = variant_values(v)
        available_colors.append(color)
        available_sizes.append(size)
        variant_rows.append({
            "variant_id": v.get("id"),
            "name": v.get("name"),
            "color": color,
            "size": size,
        })
    available_colors = uniq_preserve(available_colors)
    available_sizes = uniq_preserve(available_sizes)

    selected_colors, missing_colors = choose_requested(spec.get("colors", []), available_colors) if auto_selected else ([], spec.get("colors", []))
    selected_sizes, missing_sizes = choose_requested(spec.get("sizes", []), available_sizes) if auto_selected else ([], spec.get("sizes", []))

    selected_variant_ids = []
    if auto_selected:
        sc = {normalize(x) for x in selected_colors}
        ss = {normalize(x) for x in selected_sizes}
        for row in variant_rows:
            color_ok = not sc or normalize(row.get("color")) in sc
            size_ok = not ss or normalize(row.get("size")) in ss
            if color_ok and size_ok:
                selected_variant_ids.append(row["variant_id"])

    base.update({
        "status": "ready_for_master" if auto_selected else "review_candidates",
        "auto_selected": auto_selected,
        "match_score": winner["score"],
        "catalog_product_id": product.get("id"),
        "catalog_name": product.get("name"),
        "brand": product.get("brand"),
        "model": product.get("model"),
        "is_discontinued": product.get("is_discontinued"),
        "master_template_id": spec.get("master_template_id"),
        "selected_colors": selected_colors,
        "missing_requested_colors": missing_colors,
        "selected_sizes": selected_sizes,
        "missing_requested_sizes": missing_sizes,
        "selected_variant_ids": selected_variant_ids,
        "available_colors": available_colors,
        "available_sizes": available_sizes,
        "next_step": (
            "Reuse existing master template; apply/verify artwork manually."
            if spec.get("master_template_id")
            else "Create one clean Printful master template for this blank, then apply artwork manually."
        ) if auto_selected else "Review the ranked candidates in stage3_product_candidates.json and set catalog_product_id in product_catalog_plan.json."
    })
    return base


def write_csv(queue, path):
    fields = [
        "key", "display_name", "category", "priority", "fulfillment", "status",
        "catalog_product_id", "catalog_name", "brand", "model", "master_template_id",
        "selected_colors", "selected_sizes", "selected_variant_ids", "next_step"
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in queue:
            row = {k: item.get(k, "") for k in fields}
            for key in ("selected_colors", "selected_sizes", "selected_variant_ids"):
                if isinstance(row.get(key), list):
                    row[key] = " | ".join(str(x) for x in row[key])
            writer.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Build only one product key from product_catalog_plan.json")
    args = ap.parse_args()

    token = os.getenv("PRINTFUL_TOKEN")
    store_id = os.getenv("PRINTFUL_STORE_ID")
    if not token or not store_id:
        raise SystemExit("Set PRINTFUL_TOKEN and PRINTFUL_STORE_ID first.")
    if not PLAN_PATH.exists():
        raise SystemExit(f"Missing {PLAN_PATH}")

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    specs = plan.get("products", [])
    if args.only:
        specs = [s for s in specs if s.get("key") == args.only]
        if not specs:
            raise SystemExit(f"No product key found: {args.only}")

    print("Fetching current Printful catalog...")
    products = get_all_catalog_products(token)
    print(f"Loaded {len(products)} catalog products.")

    candidates_output = {}
    queue = []

    for spec in specs:
        print(f"\n[{spec['key']}] {spec['display_name']}")
        if spec.get("fulfillment") != "printful":
            print(f"  External/manual fulfillment: {spec.get('fulfillment')}")
            queue.append(build_queue_item(spec, [], token))
            continue

        candidates = best_candidates(spec, products)
        candidates_output[spec["key"]] = [
            {
                "score": c["score"],
                "id": c["product"].get("id"),
                "name": c["product"].get("name"),
                "brand": c["product"].get("brand"),
                "model": c["product"].get("model"),
                "is_discontinued": c["product"].get("is_discontinued"),
            }
            for c in candidates
        ]

        if candidates:
            top = candidates[0]
            print(f"  Top match: {top['product'].get('id')} | {top['product'].get('name')} | score={top['score']}")
        else:
            print("  No match found.")

        item = build_queue_item(spec, candidates, token)
        queue.append(item)
        print(f"  Status: {item['status']}")
        if item.get("selected_colors"):
            print(f"  Colors: {', '.join(item['selected_colors'])}")
        if item.get("selected_sizes"):
            print(f"  Sizes: {', '.join(item['selected_sizes'])}")
        if item.get("missing_requested_colors"):
            print(f"  Missing/needs review colors: {', '.join(item['missing_requested_colors'])}")
        if item.get("missing_requested_sizes"):
            print(f"  Missing/needs review sizes: {', '.join(item['missing_requested_sizes'])}")

    Path("stage3_product_candidates.json").write_text(json.dumps(candidates_output, indent=2), encoding="utf-8")
    Path("stage3_product_queue.json").write_text(json.dumps(queue, indent=2), encoding="utf-8")
    write_csv(queue, "stage3_product_queue.csv")

    print("\nDone.")
    print("Wrote:")
    print("  stage3_product_candidates.json")
    print("  stage3_product_queue.json")
    print("  stage3_product_queue.csv")
    print("\nInterpretation:")
    print("  ready_for_master   = product confidently identified; build the one-time Printful master")
    print("  review_candidates  = choose among ranked current Printful catalog options")
    print("  external_manual    = intentionally outside Printful")
    print("\nArtwork remains manual by design.")


if __name__ == "__main__":
    main()
