"""Tesseract-based OCR fallback for PDFs whose embedded text layer is unusable.

Two cases need OCR: (1) scanned/image-only PDFs with no text layer, and (2) PDFs
whose embedded font has no usable ToUnicode/CMap, so the text layer extracts as
mojibake even though it is dense (the takbook-style Persian books). ingest.py
detects both and asks this module to OCR the affected pages.

Backends, both chosen to avoid a heavy GPU footprint (the 8 GB GPU is already
shared by the LLM + embeddings):
  - Rendering: pypdfium2 (pip-only, bundles PDFium -- NO Poppler/system binary).
  - OCR: Tesseract via pytesseract with the Persian ('fas') model. Tesseract is a
    SYSTEM binary that must be installed separately (Windows: UB-Mannheim installer
    with the Persian language pack; Linux: `apt install tesseract-ocr tesseract-ocr-fas`).
    Set TESSERACT_CMD in .env if tesseract.exe is not on PATH.

Rendered page PNGs are written to the caller-provided out_dir (the asset's own
`ocr/` folder) so a run is inspectable and re-runnable. Nothing here touches the
DB, Chroma, or the GPU.
"""
import os
import shutil
from typing import Dict, Iterable, Tuple

OCR_LANG = os.getenv("OCR_LANG", "fas")
OCR_DPI = int(os.getenv("OCR_DPI", "300"))  # 300 DPI is the sweet spot for print OCR


def _pytesseract():
    """Import pytesseract and point it at TESSERACT_CMD if set. The env var is read
    lazily (here, not at import) so it works regardless of whether .env was loaded
    before this module was first imported, and so it can point at a tesseract.exe
    that is not on PATH."""
    import pytesseract
    cmd = os.getenv("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def availability(lang: str = OCR_LANG) -> Tuple[bool, str]:
    """(available, reason_in_persian). Verifies the renderer, the pytesseract
    wrapper, a runnable tesseract binary, and that the language pack is installed.
    Read-only -- never installs anything."""
    try:
        import pypdfium2  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"pypdfium2 در دسترس نیست ({e})"
    try:
        pt = _pytesseract()
    except Exception as e:  # noqa: BLE001
        return False, f"pytesseract نصب نیست ({e})"
    if not os.getenv("TESSERACT_CMD") and shutil.which("tesseract") is None:
        return False, ("باینری Tesseract روی PATH پیدا نشد — Tesseract را نصب کنید "
                       "یا مسیر آن را در TESSERACT_CMD بگذارید")
    try:
        langs = pt.get_languages(config="")
    except Exception as e:  # noqa: BLE001
        return False, f"اجرای Tesseract ناموفق بود ({e})"
    if lang not in langs:
        return False, (f"بسته‌ی زبان «{lang}» در Tesseract نصب نیست "
                       f"(زبان‌های موجود: {', '.join(langs) or 'هیچ'})")
    return True, ""


def ocr_pages(pdf_bytes: bytes, page_indices: Iterable[int], out_dir: str,
              lang: str = OCR_LANG, dpi: int = OCR_DPI) -> Dict[int, str]:
    """Render the given 0-based page indices to PNGs under out_dir and OCR each
    with Tesseract. Returns {page_index: recognized_text}. Raises on hard failure;
    the caller (ingest.normalize_pdf) decides the failure policy."""
    import pypdfium2 as pdfium
    pt = _pytesseract()
    os.makedirs(out_dir, exist_ok=True)
    scale = dpi / 72.0  # PDF user space is 72 units/inch
    results: Dict[int, str] = {}
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        for idx in page_indices:
            page = pdf[idx]
            pil_image = page.render(scale=scale).to_pil()
            pil_image.save(os.path.join(out_dir, f"page-{idx + 1:04d}.png"))
            results[idx] = pt.image_to_string(pil_image, lang=lang) or ""
    finally:
        pdf.close()
    return results
