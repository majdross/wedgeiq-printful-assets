#!/usr/bin/env python3
"""Bulk upload WedgeIQ production PNGs from the public GitHub repo to Printful.

Environment variables required:
  PRINTFUL_TOKEN
  PRINTFUL_STORE_ID

Run from the repository root:
  python3 scripts/printful_bulk_upload.py

Behavior:
- Scans 01_PRINTFUL_UPLOAD recursively for PNG files.
- Builds raw.githubusercontent.com URLs automatically.
- Adds a SHA-256 query-string version so changed files get a new URL.
- Uploads each file to Printful v2 Files API.
- Polls until status is ok/failed or timeout.
- Saves resumable results in printful_upload_results.json.
- Skips assets already recorded as ok with the same local SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OWNER = "majdross"
REPO = "wedgeiq-printful-assets"
BRANCH = "main"
ASSET_ROOT = Path("01_PRINTFUL_UPLOAD")
RESULTS_FILE = Path("printful_upload_results.json")
API_BASE = "https://api.printful.com/v2/files"
POLL_SECONDS = 4
POLL_TIMEOUT_SECONDS = 180


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def raw_url(path: Path, digest: str) -> str:
    rel = path.as_posix()
    quoted = "/".join(urllib.parse.quote(part) for part in rel.split("/"))
    return f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{quoted}?v={digest[:16]}"


def request_json(method: str, url: str, token: str, store_id: str, payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-PF-Store-Id": store_id,
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e}") from e


def load_results() -> dict:
    if not RESULTS_FILE.exists():
        return {"repo": f"{OWNER}/{REPO}", "branch": BRANCH, "files": {}}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"repo": f"{OWNER}/{REPO}", "branch": BRANCH, "files": {}}


def save_results(results: dict) -> None:
    RESULTS_FILE.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")


def poll_file(file_id: int, token: str, store_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT_SECONDS
    last = None
    while time.time() < deadline:
        response = request_json("GET", f"{API_BASE}/{file_id}", token, store_id)
        data = response.get("data", {})
        status = data.get("status")
        last = data
        if status in {"ok", "failed"}:
            return data
        time.sleep(POLL_SECONDS)
    return last or {"id": file_id, "status": "timeout"}


def main() -> int:
    token = os.environ.get("PRINTFUL_TOKEN")
    store_id = os.environ.get("PRINTFUL_STORE_ID")
    if not token:
        print("ERROR: PRINTFUL_TOKEN is not set.", file=sys.stderr)
        return 2
    if not store_id:
        print("ERROR: PRINTFUL_STORE_ID is not set.", file=sys.stderr)
        return 2
    if not ASSET_ROOT.exists():
        print(f"ERROR: {ASSET_ROOT} not found. Run this from the repository root.", file=sys.stderr)
        return 2

    files = sorted(p for p in ASSET_ROOT.rglob("*.png") if p.is_file())
    if not files:
        print("No PNG assets found.")
        return 0

    results = load_results()
    records = results.setdefault("files", {})

    print(f"Found {len(files)} PNG assets.")
    print("Uploading to Printful...\n")

    ok = skipped = failed = 0

    for index, path in enumerate(files, start=1):
        rel = path.as_posix()
        digest = sha256_file(path)
        previous = records.get(rel, {})

        if previous.get("sha256") == digest and previous.get("status") == "ok":
            skipped += 1
            print(f"[{index}/{len(files)}] SKIP {rel} (already OK)")
            continue

        url = raw_url(path, digest)
        print(f"[{index}/{len(files)}] UPLOAD {rel}")

        try:
            created = request_json(
                "POST",
                API_BASE,
                token,
                store_id,
                {
                    "role": "printfile",
                    "url": url,
                    "filename": path.name,
                    "visible": True,
                },
            ).get("data", {})

            file_id = created.get("id")
            if not file_id:
                raise RuntimeError(f"No Printful file ID returned: {created}")

            records[rel] = {
                "sha256": digest,
                "source_url": url,
                "printful_file_id": file_id,
                "status": created.get("status", "waiting"),
                "filename": path.name,
            }
            save_results(results)

            final = poll_file(file_id, token, store_id)
            records[rel].update({
                "status": final.get("status"),
                "mime_type": final.get("mime_type"),
                "size": final.get("size"),
                "width": final.get("width"),
                "height": final.get("height"),
                "dpi": final.get("dpi"),
                "thumbnail_url": final.get("thumbnail_url"),
                "preview_url": final.get("preview_url"),
            })
            save_results(results)

            if final.get("status") == "ok":
                ok += 1
                print(f"    OK id={file_id} {final.get('width')}x{final.get('height')}")
            else:
                failed += 1
                print(f"    {str(final.get('status')).upper()} id={file_id}")

        except Exception as exc:
            failed += 1
            records[rel] = {
                "sha256": digest,
                "source_url": url,
                "filename": path.name,
                "status": "error",
                "error": str(exc),
            }
            save_results(results)
            print(f"    ERROR: {exc}")

    print("\nDone.")
    print(f"OK: {ok} | Skipped: {skipped} | Failed/Timeout: {failed}")
    print(f"Results: {RESULTS_FILE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
