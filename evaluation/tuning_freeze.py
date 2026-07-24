"""Hash-based tuning freeze guard for a single held-out execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_manifest(root: Path, paths: list[Path]) -> dict:
    return {
        "version": 1,
        "files": {
            path.relative_to(root).as_posix(): file_sha256(path)
            for path in sorted(paths)
        },
    }


def verify_manifest(root: Path, manifest: dict) -> list[str]:
    mismatches = []
    for relative, expected in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file() or file_sha256(path) != expected:
            mismatches.append(relative)
    return mismatches


def write_manifest(root: Path, paths: list[Path], output: Path) -> dict:
    manifest = create_manifest(root, paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
