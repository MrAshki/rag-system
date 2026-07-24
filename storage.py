"""Per-user, per-category file storage layout.

Single source of truth for WHERE a user's uploaded asset and its derived
artifacts live on disk. Replaces the old flat `docs/` (originals) + `converted/`
(normalized markdown + metadata) directories, which dumped every user's files
together with no ownership structure.

Layout:

    storage/{user_id}/{category}/{asset_id}/
        original.{ext}     # the uploaded file, byte-for-byte
        normalized.md      # text pipeline output (text category only)
        metadata.json      # normalization metadata sidecar (text category only)

`category` is derived from the file extension (text|image|audio|video). Only the
`text` category currently has a scan/index pipeline; media is stored as-is so a
future pipeline (OCR, transcription, ...) can process it in place without a
re-upload. Nothing here knows about the DB or Chroma -- it is pure path logic.
"""
import os
from typing import Optional

STORAGE_ROOT = os.getenv("STORAGE_ROOT", "./storage")

# Extension -> category. Lower-case, leading dot, exactly as os.path.splitext yields.
CATEGORY_BY_EXT = {
    # text (the only category with a scan/normalize/index pipeline today)
    ".txt": "text", ".pdf": "text", ".docx": "text",
    # image
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image",
    # audio
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
    # video
    ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video", ".avi": "video",
}

# Categories that currently have a scan pipeline (normalize -> chunk -> index).
# An asset in any other category is stored verbatim and marked 'stored', not scanned.
PROCESSABLE_CATEGORIES = {"text"}

# Every accepted upload extension, derived from the mapping above (no second list to drift).
ALLOWED_EXTENSIONS = set(CATEGORY_BY_EXT.keys())


def category_for_ext(ext: str) -> Optional[str]:
    """Map a file extension (with leading dot, any case) to its category, or None
    if the extension is not an accepted upload type."""
    return CATEGORY_BY_EXT.get((ext or "").lower())


def is_processable(category: str) -> bool:
    return category in PROCESSABLE_CATEGORIES


def asset_dir(user_id, category: str, asset_id: str, create: bool = True) -> str:
    """Absolute-ish path to one asset's own folder. Creates it (and parents) by
    default so callers never have to os.makedirs themselves."""
    path = os.path.join(STORAGE_ROOT, str(user_id), category, asset_id)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def original_path(user_id, category: str, asset_id: str, ext: str) -> str:
    """Path to the verbatim uploaded file, named original.{ext}."""
    return os.path.join(asset_dir(user_id, category, asset_id), f"original{(ext or '').lower()}")


def normalized_md_path(user_id, category: str, asset_id: str) -> str:
    """Path to the canonical normalized Markdown (text pipeline output)."""
    return os.path.join(asset_dir(user_id, category, asset_id), "normalized.md")


def metadata_path(user_id, category: str, asset_id: str) -> str:
    """Path to the normalization metadata sidecar JSON."""
    return os.path.join(asset_dir(user_id, category, asset_id), "metadata.json")


def document_map_path(user_id, category: str, asset_id: str) -> str:
    """Path to the stable parent-unit map consumed by agentic RAG."""
    return os.path.join(asset_dir(user_id, category, asset_id), "document_map.json")


def ocr_dir(user_id, category: str, asset_id: str, create: bool = False) -> str:
    """Folder for OCR image-processing artifacts (rendered page PNGs). Kept in a
    SEPARATE subfolder from the normalize pipeline's normalized.md/metadata.json:
    those are pipeline output and live at the asset root, while rendered page
    images are image-processing intermediates and live under {asset}/ocr/. Not
    created by default (clean PDFs never need OCR, so they get no ocr/ folder);
    the OCR backend creates it only when it actually renders pages."""
    path = os.path.join(asset_dir(user_id, category, asset_id, create=create), "ocr")
    if create:
        os.makedirs(path, exist_ok=True)
    return path
