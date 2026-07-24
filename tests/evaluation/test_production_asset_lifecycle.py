from pathlib import Path

from evaluation.runners import evaluate_production_baseline as runner


def test_asset_match_requires_owner_name_size_and_hash(tmp_path, monkeypatch):
    source = tmp_path / "fixture.pdf"
    source.write_bytes(b"trusted bytes")
    stored = tmp_path / "stored.pdf"
    stored.write_bytes(b"trusted bytes")
    row = {
        "id": "asset-1",
        "user_id": 7,
        "original_filename": source.name,
        "size_bytes": source.stat().st_size,
        "original_path": str(stored),
        "status": "scanned",
        "processing_version": f"{runner.ingest.NORMALIZATION_VERSION}:profile:map",
    }
    monkeypatch.setattr(runner.db, "get_asset", lambda asset_id: row if asset_id == "asset-1" else None)

    assert runner._asset_matches_source("asset-1", user_id=7, source=source)
    assert not runner._asset_matches_source("asset-1", user_id=8, source=source)
    stored.write_bytes(b"altered bytes")
    assert not runner._asset_matches_source("asset-1", user_id=7, source=source)


def test_scanned_asset_from_old_normalizer_is_not_reused(tmp_path, monkeypatch):
    source = tmp_path / "fixture.pdf"
    source.write_bytes(b"trusted bytes")
    row = {
        "id": "asset-1",
        "user_id": 7,
        "original_filename": source.name,
        "size_bytes": source.stat().st_size,
        "original_path": str(source),
        "status": "scanned",
        "processing_version": "v4:profile:map",
    }
    monkeypatch.setattr(runner.db, "get_asset", lambda _asset_id: row)
    assert not runner._asset_matches_source("asset-1", user_id=7, source=source)


def test_asset_match_rejects_stale_or_missing_database_mapping(tmp_path, monkeypatch):
    source = tmp_path / "fixture.pdf"
    source.write_bytes(b"source")
    monkeypatch.setattr(runner.db, "get_asset", lambda _asset_id: None)

    assert not runner._asset_matches_source("stale-id", user_id=7, source=source)
