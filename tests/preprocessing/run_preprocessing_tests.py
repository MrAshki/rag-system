"""Run the document preprocessing pipeline (ingest -> chunker) on the fixtures and
verify the output is clean. Does NOT touch Chroma, Ollama, or the embedding model --
this is a pure text-preprocessing test.

Run:  .\\venv\\Scripts\\python.exe tests\\preprocessing\\run_preprocessing_tests.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")

from document_pipeline import ingest, chunker  # noqa: E402

FIXDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
HEADING_LINE_RE = re.compile(r"^(#{1,3})\s+(.*)$")

failures = []


def check(cond, msg):
    status = "PASS" if cond else "FAIL"
    print(f"   [{status}] {msg}")
    if not cond:
        failures.append(msg)


def run_one(filename, ext):
    print("=" * 90)
    print(f"FIXTURE: {filename}")
    with open(os.path.join(FIXDIR, filename), "rb") as f:
        result = ingest.normalize_document(filename, f, ext)
    md = result["markdown_text"]
    meta = result["meta"]

    headings = [(len(m.group(1)), m.group(2)) for line in md.splitlines()
                if (m := HEADING_LINE_RE.match(line.strip()))]
    print(f"  extraction={meta.get('extraction_method')} confidence={meta.get('structure_confidence')} "
          f"headings={meta.get('heading_count')} pages={meta.get('page_count')}")
    print("  --- detected headings (level | text) ---")
    for lvl, txt in headings:
        print(f"     h{lvl} | {txt}")

    # 1) no boilerplate leaked as content/heading
    check("# []" not in md and "\n[]" not in md and not md.startswith("[]"),
          "junk '[]' line removed")
    check("[Cover" not in md, "'[Cover ...]' image-alt line removed")
    # 2) no paragraph-as-heading: every detected heading is short
    check(all(len(txt) <= 120 for _, txt in headings),
          "no over-long heading (paragraph-as-heading) in markdown")
    # 3) the adversarial 'Part ...' / 'Chapter 3 ...' paragraphs stayed body text
    for needle in ["Part of the difficulty", "Part of the analysis", "Part of the methodology",
                   "Chapter 3 covered how"]:
        if needle in md:
            in_heading = any(needle in txt for _, txt in headings)
            check(not in_heading, f"paragraph starting '{needle[:18]}...' stayed body text")

    # chunk-level metadata must also be clean
    chunks = chunker.parse_markdown_to_chunks(md)
    bad = [c for c in chunks
           for v in (c.get("chapter"), c.get("section"), c.get("subsection"))
           if v and len(str(v)) > 120]
    check(not bad, f"all chunk chapter/section/subsection labels are short ({len(chunks)} chunks)")
    print(f"  --- {len(chunks)} chunks; sample labels ---")
    for c in chunks[:4]:
        print(f"     chunk {c['chunk_index']}: chapter={c.get('chapter')!r} "
              f"section={c.get('section')!r} subsection={c.get('subsection')!r} page={c.get('page')!r}")
    return md


def main():
    md_txt = run_one("sample.txt", ".txt")
    run_one("sample.docx", ".docx")
    run_one("sample.pdf", ".pdf")

    # Persian must survive intact end-to-end (UTF-8 fidelity).
    print("=" * 90)
    check("مبانی" in md_txt and "پاراگراف فارسی" in md_txt, "Persian text preserved (UTF-8 intact)")
    check("فصل ۲: مبانی" in md_txt, "real Persian heading 'فصل ۲: مبانی' detected/preserved")

    print("=" * 90)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("RESULT: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
