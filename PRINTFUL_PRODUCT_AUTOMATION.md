# WedgeIQ Printful Product Automation

This workflow automates product selection and variant planning while keeping artwork/logo placement manual.

## Files

- `product_catalog_plan.json` — source of truth for recommended WedgeIQ products.
- `scripts/stage3_build_recommended_product_queue.py` — current Printful catalog discovery + validation script.
- `stage3_product_candidates.json` — ranked Printful candidates when a product is ambiguous.
- `stage3_product_queue.json` — detailed build queue.
- `stage3_product_queue.csv` — easy review version of the build queue.

## Recommended products covered

- Next Level 3600 Performance Tee
- Cotton Heritage M2580 Hoodie
- adidas Performance Golf Polo
- Sport-Tek ST357 Performance 1/4 Zip
- Lane Seven LS14014 Premium 1/4 Zip
- Comfort Colors 1566 Crewneck
- Columbia / soft-shell outerwear candidate
- 16 × 24 Golf Towel
- AOP Duffle
- Premium Hat is retained as the existing Reach/manual manufacturing path

## Run it

From the repo root:

```bash
cd /Users/majdross/Documents/GitHub/wedgeiq-printful-assets
python3 scripts/stage3_build_recommended_product_queue.py
```

To inspect only one product family:

```bash
python3 scripts/stage3_build_recommended_product_queue.py --only quarter_zip_performance
```

Environment variables must already exist locally:

- `PRINTFUL_TOKEN`
- `PRINTFUL_STORE_ID`

Do not commit either secret to GitHub.

## What the script does

1. Pulls the current Printful Catalog v2.
2. Uses exact catalog IDs when already proven.
3. Otherwise matches products by brand, model, and search terms.
4. Pulls current North American variants.
5. Checks requested WedgeIQ launch colors and sizes against Printful's current variants.
6. Produces a product queue with catalog product IDs and selected variant IDs.
7. Flags ambiguous products for quick review instead of guessing.

## Status meanings

- `ready_for_master` — Printful product was confidently identified. Create the one-time clean master template, then apply artwork manually.
- `review_candidates` — multiple Printful products could fit. Review `stage3_product_candidates.json`, choose one, and put its `catalog_product_id` into `product_catalog_plan.json`.
- `external_manual` — product intentionally remains outside Printful automation.

## WedgeIQ workflow

```text
product_catalog_plan.json
        ↓
Current Printful Catalog
        ↓
Product + Variant Validation
        ↓
stage3_product_queue.json / .csv
        ↓
One-time Printful Master Template
        ↓
Manual WedgeIQ Artwork
        ↓
Sample / Validate
        ↓
Publish
        ↓
Shopify V2
```

## Why artwork is manual

Product selection, colors, sizes, and catalog matching are deterministic and useful to automate. Artwork placement is intentionally manual because Printful's template/design-layer workflow has been less reliable for the WedgeIQ use case and visual placement needs a human check.

## Adding a new WedgeIQ product later

Add one new object under `products` in `product_catalog_plan.json` with:

- `key`
- `display_name`
- `category`
- `priority`
- `fulfillment`
- `preferred_brand`
- `preferred_model`
- `search_terms`
- `colors`
- `sizes`
- `technique_preference`

Then rerun the script. No new product-specific script is required.
