#!/usr/bin/env python3
"""Stage 4: prepare the one-time Printful master-template setup queue.

This script intentionally stops short of placing artwork or trying to create brand-new
Printful Product Templates via API. Printful's API is reliable for duplicating an
existing Product Template, but not for creating every new template from scratch.

Workflow:
  1. Run stage3_build_recommended_product_queue.py
  2. Run this script
  3. Create only the missing ONE-TIME masters in Printful manually
  4. Record the resulting template IDs in product_master_registry.json
  5. Future automation can duplicate those masters at scale

Inputs:
  stage3_product_queue.json
  product_catalog_plan.json

Outputs:
  stage4_master_setup_queue.json
  stage4_master_setup_queue.csv
  STAGE4_MASTER_SETUP.md

Usage:
  python3 scripts/stage4_prepare_master_setup.py
"""

import csv
import json
from pathlib import Path

QUEUE_PATH = Path("stage3_product_queue.json")
PLAN_PATH = Path("product_catalog_plan.json")
REGISTRY_PATH = Path("product_master_registry.json")
OUT_JSON = Path("stage4_master_setup_queue.json")
OUT_CSV = Path("stage4_master_setup_queue.csv")
OUT_MD = Path("STAGE4_MASTER_SETUP.md")


def load_json(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_registry(plan):
    existing = load_json(REGISTRY_PATH, {}) or {}
    changed = False

    if "brand" not in existing:
        existing["brand"] = "WedgeIQ"
        changed = True
    if "version" not in existing:
        existing["version"] = "1.0"
        changed = True
    if "masters" not in existing:
        existing["masters"] = {}
        changed = True

    masters = existing["masters"]
    for spec in plan.get("products", []):
        if spec.get("fulfillment") != "printful":
            continue
        key = spec["key"]
        if key not in masters:
            masters[key] = {
                "catalog_product_id": spec.get("catalog_product_id"),
                "template_id": spec.get("master_template_id"),
                "status": "existing" if spec.get("master_template_id") else "needs_master",
                "artwork": "manual",
                "notes": ""
            }
            changed = True
        else:
            if spec.get("catalog_product_id") and not masters[key].get("catalog_product_id"):
                masters[key]["catalog_product_id"] = spec.get("catalog_product_id")
                changed = True
            if spec.get("master_template_id") and not masters[key].get("template_id"):
                masters[key]["template_id"] = spec.get("master_template_id")
                masters[key]["status"] = "existing"
                changed = True

    if changed:
        REGISTRY_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return existing


def join_list(value):
    if not value:
        return ""
    if isinstance(value, list):
        return " | ".join(str(x) for x in value)
    return str(value)


def main():
    if not QUEUE_PATH.exists():
        raise SystemExit(
            "Missing stage3_product_queue.json. Run:\n"
            "  python3 scripts/stage3_build_recommended_product_queue.py"
        )
    if not PLAN_PATH.exists():
        raise SystemExit(f"Missing {PLAN_PATH}")

    queue = load_json(QUEUE_PATH, []) or []
    plan = load_json(PLAN_PATH, {}) or {}
    registry = ensure_registry(plan)
    masters = registry.get("masters", {})

    rows = []
    for item in queue:
        key = item.get("key")
        fulfillment = item.get("fulfillment")
        if fulfillment != "printful":
            continue

        reg = masters.get(key, {})
        template_id = reg.get("template_id") or item.get("master_template_id")

        if item.get("status") not in {"ready_for_master", "review_candidates"}:
            action = "hold"
        elif template_id:
            action = "master_exists"
        elif item.get("status") == "review_candidates":
            action = "resolve_product_first"
        else:
            action = "create_one_time_master"

        rows.append({
            "key": key,
            "display_name": item.get("display_name"),
            "priority": item.get("priority"),
            "action": action,
            "catalog_product_id": item.get("catalog_product_id"),
            "catalog_name": item.get("catalog_name"),
            "brand": item.get("brand"),
            "model": item.get("model"),
            "selected_colors": item.get("selected_colors", []),
            "selected_sizes": item.get("selected_sizes", []),
            "selected_variant_ids": item.get("selected_variant_ids", []),
            "template_id": template_id,
            "artwork": "manual",
            "next_step": (
                "No master creation needed. Keep this template as the reusable source."
                if action == "master_exists" else
                "In Printful, create ONE Product Template using this catalog product, selected colors/sizes, and your preferred technique. Apply artwork manually. Then paste the resulting template ID into product_master_registry.json."
                if action == "create_one_time_master" else
                "Resolve/lock the catalog product before creating a master."
                if action == "resolve_product_first" else
                "Hold until Stage 3 marks the product ready."
            )
        })

    OUT_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    fields = [
        "key", "display_name", "priority", "action", "catalog_product_id", "catalog_name",
        "brand", "model", "selected_colors", "selected_sizes", "selected_variant_ids",
        "template_id", "artwork", "next_step"
    ]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["selected_colors"] = join_list(out["selected_colors"])
            out["selected_sizes"] = join_list(out["selected_sizes"])
            out["selected_variant_ids"] = join_list(out["selected_variant_ids"])
            writer.writerow(out)

    md = [
        "# WedgeIQ Stage 4 — Printful Master Setup",
        "",
        "Artwork remains manual by design. This stage only organizes the one-time Product Template setup required before the rest can be duplicated/automated.",
        "",
        "## Master status",
        ""
    ]

    for row in rows:
        md.append(f"### {row['display_name']}")
        md.append(f"- Action: **{row['action']}**")
        md.append(f"- Printful catalog product: **{row.get('catalog_product_id')} — {row.get('catalog_name')}**")
        if row.get("selected_colors"):
            md.append(f"- Colors: {', '.join(row['selected_colors'])}")
        if row.get("selected_sizes"):
            md.append(f"- Sizes: {', '.join(row['selected_sizes'])}")
        if row.get("template_id"):
            md.append(f"- Existing master template ID: **{row['template_id']}**")
        md.append(f"- Next: {row['next_step']}")
        md.append("")

    md.extend([
        "## After you create each missing master",
        "",
        "Open `product_master_registry.json` and enter the Printful Product Template ID for that product. Example:",
        "",
        "```json",
        '"hoodie": {',
        '  "catalog_product_id": 380,',
        '  "template_id": 123456789,',
        '  "status": "existing",',
        '  "artwork": "manual",',
        '  "notes": "Approved master"',
        '}',
        "```",
        "",
        "Once every launch product has a template ID, Stage 5 can use those masters for automatic duplication and future product-family expansion."
    ])
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print("Stage 4 complete.")
    print("Wrote:")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_CSV}")
    print(f"  {OUT_MD}")
    print(f"  {REGISTRY_PATH}")
    print("\nActions:")
    for row in rows:
        print(f"  [{row['action']}] {row['display_name']} | catalog_id={row['catalog_product_id']} | template_id={row['template_id']}")
    print("\nCreate only the rows marked create_one_time_master. Artwork stays manual.")


if __name__ == "__main__":
    main()
