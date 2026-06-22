import os
import uuid
from flask import Flask, request, jsonify
from pypdf import PdfReader
from docx import Document as DocxDocument
import rag

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}


def fa_number(n: int) -> str:
    return str(n).translate(PERSIAN_DIGITS)


def extract_text(file) -> str:
    """Extract plain text from an uploaded .txt/.pdf/.docx file. Raises ValueError
    on unsupported types or extraction failure."""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".txt":
        return file.stream.read().decode("utf-8")
    if ext == ".pdf":
        reader = PdfReader(file.stream)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        doc = DocxDocument(file.stream)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    raise ValueError(f"Unsupported file type: {ext}")


DOCS_DIR = "./docs"
os.makedirs(DOCS_DIR, exist_ok=True)

app = Flask(__name__, static_folder="webapp", static_url_path="")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/documents", methods=["GET"])
def list_documents():
    return jsonify({"documents": rag.list_documents()})


@app.route("/api/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "فایلی انتخاب نشده است"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "فقط فایل‌های .txt، .pdf و .docx پشتیبانی می‌شوند"}), 400

    try:
        text = extract_text(file)
    except Exception as e:
        return jsonify({"error": f"خطا در استخراج متن از فایل: {str(e)}"}), 400

    if not text.strip():
        return jsonify({"error": "متنی از فایل استخراج نشد (ممکن است اسکن‌شده باشد)"}), 400

    document_id = uuid.uuid4().hex
    # Always store the extracted plain text on disk by document_id, regardless of
    # the original format, so two uploads with the same filename never collide
    # and the rest of the pipeline only ever deals with plain UTF-8 text.
    path = os.path.join(DOCS_DIR, f"{document_id}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    result = rag.index_document(file.filename, text, document_id=document_id)

    return jsonify({
        "status": "ok",
        "filename": file.filename,
        "document_id": document_id,
        "chunks": result["chunks"],
    })


@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    scope = data.get("scope", "all")
    document_id = data.get("document_id")
    document_name = data.get("document_name")

    if not question:
        return jsonify({"error": "سوال خالی است"}), 400
    if scope == "selected" and not document_id:
        return jsonify({"error": "برای این حالت باید یک سند انتخاب شود"}), 400

    doc_filter = document_id if scope == "selected" else None
    sub_questions = rag.split_questions(question)

    if len(sub_questions) <= 1:
        chunks = rag.query_documents(question, document_id=doc_filter)
        result = rag.generate_response(question, chunks, scope=scope, selected_source=document_name)
        return jsonify(result)

    # Mixed multi-question input: answer each part independently so one
    # unanswerable part doesn't cause a full refusal of the whole input.
    answer_lines = []
    all_sources = []
    for i, part in enumerate(sub_questions, start=1):
        chunks = rag.query_documents(part, document_id=doc_filter)
        sub = rag.generate_response(part, chunks, scope=scope, selected_source=document_name)
        line = f"{fa_number(i)}. {sub['answer']}"
        if sub["sources"]:
            line += "\nمنبع: " + "، ".join(sub["sources"])
        answer_lines.append(line)
        all_sources.extend(sub["sources"])

    return jsonify({"answer": "\n\n".join(answer_lines), "sources": all_sources})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
