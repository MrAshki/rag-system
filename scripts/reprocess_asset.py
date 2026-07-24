import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
import rag
import scan_worker


def _matches(asset, filename_part: str) -> bool:
    if not filename_part:
        return True
    return filename_part.lower() in (asset["original_filename"] or "").lower()


def _candidate_assets(user_id: int | None, asset_id: str | None, filename_part: str | None):
    if asset_id:
        asset = db.get_asset(asset_id)
        return [asset] if asset else []
    if user_id is None:
        raise SystemExit("--user-id is required when --asset-id is not provided")
    return [
        asset
        for asset in db.list_assets(user_id, category="text")
        if _matches(asset, filename_part or "")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-normalize and re-index text assets.")
    parser.add_argument("--asset-id", help="Asset id to reprocess.")
    parser.add_argument("--user-id", type=int, help="Owner user id, required without --asset-id.")
    parser.add_argument("--filename-contains", help="Filter assets by original filename substring.")
    parser.add_argument("--include-failed", action="store_true", help="Also reprocess failed assets.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    args = parser.parse_args()

    assets = [
        asset
        for asset in _candidate_assets(args.user_id, args.asset_id, args.filename_contains)
        if asset
        and asset["category"] == "text"
        and (args.include_failed or asset["status"] in {"scanned", "uploaded", "scanning"})
    ]
    if not assets:
        print("No matching text assets found.")
        return 1

    print("Assets to reprocess:")
    for asset in assets:
        print(f"- {asset['id']} user={asset['user_id']} status={asset['status']} file={asset['original_filename']}")

    if not args.yes:
        answer = input("Delete old vectors and reprocess these assets? Type YES: ")
        if answer != "YES":
            print("Cancelled.")
            return 1

    for asset in assets:
        asset_id = asset["id"]
        print(f"\nReprocessing {asset_id} ({asset['original_filename']})...")
        removed = rag.delete_document_index(asset_id, user_id=asset["user_id"])
        print(f"Removed {removed} existing vector point(s).")
        fresh = db.prepare_asset_for_rescan(asset_id)
        if not fresh:
            print(f"Could not mark {asset_id} for rescan.")
            continue
        scan_worker.process_asset(fresh)
        updated = db.get_asset(asset_id)
        print(
            f"Done: status={updated['status']} chunks={updated['chunk_count']} "
            f"error={updated['scan_error'] or ''}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
