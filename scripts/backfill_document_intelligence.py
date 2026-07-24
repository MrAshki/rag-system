"""Build profiles/maps for already-normalized assets without spending API quota.

Use --reindex only when Qdrant payloads also need the new parent metadata; that
mode regenerates embeddings and can consume external provider quota.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402
import storage  # noqa: E402
from document_pipeline import chunker, document_map, ingest, profiling  # noqa: E402


def backfill(asset, *, reindex: bool) -> dict:
    md_path = asset["normalized_md_path"]
    if not md_path or not os.path.exists(md_path):
        return {"id": asset["id"], "status": "skipped", "reason": "normalized.md missing"}
    with open(md_path, "r", encoding="utf-8") as handle:
        markdown = handle.read()

    meta_path = storage.metadata_path(asset["user_id"], "text", asset["id"])
    metadata = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)

    profile = profiling.profile_document(markdown, metadata, filename=asset["original_filename"])
    doc_map = document_map.build_document_map(markdown, profile)
    map_path = storage.document_map_path(asset["user_id"], "text", asset["id"])
    document_map.write_document_map(map_path, doc_map)

    metadata["document_profile"] = profile.to_dict()
    metadata["document_map_path"] = map_path
    metadata["processing_version"] = f"{ingest.NORMALIZATION_VERSION}:{profile.version}:{doc_map['version']}"
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    chunks = chunker.parse_markdown_to_chunks(markdown)
    document_map.assign_chunks_to_units(chunks, doc_map)
    if reindex:
        import rag

        rag.delete_document_index(asset["id"], user_id=asset["user_id"])
        rag.index_chunks(
            filename=asset["original_filename"],
            chunks=chunks,
            document_id=asset["id"],
            user_id=asset["user_id"],
            source_file_type=asset["file_ext"].lstrip("."),
            normalized_md_path=md_path,
        )

    db.update_asset_status(
        asset["id"],
        "scanned",
        document_profile=profile.to_dict(),
        document_map_path=map_path,
        processing_version=metadata["processing_version"],
        content_hash=profile.content_hash,
        quality_status=profile.quality.status,
        quality_score=profile.quality.score,
    )
    return {
        "id": asset["id"],
        "status": "updated",
        "type": profile.document_type,
        "quality": profile.quality.status,
        "units": len(doc_map["units"]),
        "chunks": len(chunks),
        "reindexed": reindex,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()
    assets = db.list_scanned_text_assets()
    for asset in assets:
        print(json.dumps(backfill(asset, reindex=args.reindex), ensure_ascii=False))
    print(f"Processed {len(assets)} scanned text asset(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
