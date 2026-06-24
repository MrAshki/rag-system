import os
import re
import uuid
import torch
from dotenv import load_dotenv
import chromadb
from chromadb.utils import embedding_functions
import ollama
import sys
from typing import List, Dict, Optional

import chunker

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

def _require_env(name: str) -> str:
    """Fail fast instead of silently falling back to a different model.
    A silent default here previously meant Chroma's default all-MiniLM-L6-v2
    or Ollama's llama3.2 could get used by accident if .env was misconfigured
    -- for embeddings that would silently corrupt the index (queries embedded
    with one model against vectors built with another)."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to .env before running "
            f"(expected EMBEDDING_MODEL=./models/bge-m3 and OLLAMA_MODEL=gemma3:12b)."
        )
    return value


EMBEDDING_MODEL = _require_env("EMBEDDING_MODEL")
OLLAMA_MODEL = _require_env("OLLAMA_MODEL")
COLLECTION_NAME = "document_qa_collection_local"

if torch.cuda.is_available():
    EMBEDDING_DEVICE = "cuda"
    print(f"Embedding device: cuda - {torch.cuda.get_device_name(0)}")
else:
    EMBEDDING_DEVICE = "cpu"
    print("Embedding device: cpu")

try:
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL, device=EMBEDDING_DEVICE
    )
    chroma_client = chromadb.PersistentClient(path="chroma_persistent_storage")
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME, embedding_function=embedding_fn
    )
except Exception as e:
    print(f"Error initializing clients: {str(e)}")
    sys.exit(1)


def split_text(text: str, chunk_size: int = 800, chunk_overlap: int = 150) -> List[str]:
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - chunk_overlap
    return chunks


def index_document(filename: str, text: str, document_id: Optional[str] = None, user_id: int = None) -> Dict:
    """Chunk a document and upsert it under a stable document_id, tagged with the
    owning user_id, so two documents that happen to share a filename never collide,
    and so one user's documents are never visible to another user."""
    document_id = document_id or uuid.uuid4().hex
    chunks = split_text(text)
    print(f"Indexing '{filename}' ({len(chunks)} chunks) on {EMBEDDING_DEVICE} for user_id={user_id}...", flush=True)
    for i, chunk in enumerate(chunks):
        collection.upsert(
            ids=[f"{document_id}_chunk{i+1}"],
            documents=[chunk],
            metadatas=[{
                "document_id": document_id,
                "source": filename,
                "chunk": i + 1,
                "user_id": user_id,
            }],
        )
        if (i + 1) % 50 == 0 or (i + 1) == len(chunks):
            print(f"  {filename}: {i+1}/{len(chunks)} chunks indexed", flush=True)
    return {"document_id": document_id, "chunks": len(chunks)}


def index_chunks(
    filename: str,
    chunks: List[Dict],
    document_id: Optional[str] = None,
    user_id: int = None,
    source_file_type: str = None,
    normalized_md_path: str = None,
) -> Dict:
    """Index pre-built structure-aware chunks (from chunker.parse_markdown_to_chunks)
    under a stable document_id. Each chunk's stored/embedded text gets the short
    contextual header (chapter/section/page) prepended via chunker.build_embedded_text,
    and the same fields are kept as queryable metadata."""
    document_id = document_id or uuid.uuid4().hex
    print(f"Indexing '{filename}' ({len(chunks)} structured chunks) on {EMBEDDING_DEVICE} for user_id={user_id}...", flush=True)
    for i, ch in enumerate(chunks):
        metadata = {
            "document_id": document_id,
            "source": filename,
            "chunk": ch["chunk_index"],
            "user_id": user_id,
            "source_file_type": source_file_type,
            "normalized_md_path": normalized_md_path,
            "chapter": ch.get("chapter"),
            "section": ch.get("section"),
            "subsection": ch.get("subsection"),
            "page": ch.get("page"),
            "char_start": ch.get("char_start"),
            "char_end": ch.get("char_end"),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        collection.upsert(
            ids=[f"{document_id}_chunk{ch['chunk_index']}"],
            documents=[chunker.build_embedded_text(ch)],
            metadatas=[metadata],
        )
        if (i + 1) % 50 == 0 or (i + 1) == len(chunks):
            print(f"  {filename}: {i+1}/{len(chunks)} chunks indexed", flush=True)
    return {"document_id": document_id, "chunks": len(chunks)}


def list_documents(user_id: int = None) -> List[Dict]:
    """Return the distinct indexed documents as {document_id, source} for UI display.
    Scoped to a single user's documents unless user_id is None (admin/internal use)."""
    where = {"user_id": user_id} if user_id is not None else None
    data = collection.get(where=where, include=["metadatas"])
    seen = {}
    for m in data["metadatas"]:
        if m and m.get("document_id") and m["document_id"] not in seen:
            seen[m["document_id"]] = m.get("source", "نامشخص")
    return [
        {"document_id": doc_id, "source": source}
        for doc_id, source in sorted(seen.items(), key=lambda kv: kv[1])
    ]


def split_questions(text: str) -> List[str]:
    """Split a possibly mixed multi-question input into separate sub-questions on ؟ / ? / newlines.
    A normal single question (one mark, at the end) still yields exactly one part."""
    parts = re.split(r"[؟?]+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def query_documents(question: str, n_results: int = 5, document_id: str = None, user_id: int = None) -> List[Dict]:
    try:
        conditions = []
        if user_id is not None:
            conditions.append({"user_id": user_id})
        if document_id:
            conditions.append({"document_id": document_id})

        if len(conditions) == 0:
            where = None
        elif len(conditions) == 1:
            where = conditions[0]
        else:
            where = {"$and": conditions}

        results = collection.query(
            query_texts=[question],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas"],
        )
        chunks = []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []
        for doc, meta in zip(docs, metas):
            meta = meta or {}
            chunks.append({
                "text": doc,
                "source": meta.get("source", "نامشخص"),
                "chunk": meta.get("chunk", "?"),
                "chapter": meta.get("chapter"),
                "section": meta.get("section"),
                "subsection": meta.get("subsection"),
                "page": meta.get("page"),
            })
        return chunks
    except Exception as e:
        print(f"Error querying documents: {str(e)}")
        return []


def _citation_label(chunk: Dict) -> str:
    """Builds a citation string: filename — chapter — section — p.N — chunk N,
    falling back to the old 'filename — chunk N' format when no chapter/
    section/page metadata is available (e.g. for chunks indexed before Step 2)."""
    parts = [chunk["source"]]
    if chunk.get("chapter"):
        parts.append(chunk["chapter"])
    if chunk.get("section"):
        parts.append(chunk["section"])
    if chunk.get("page"):
        parts.append(f"p.{chunk['page']}")
    parts.append(f"chunk {chunk['chunk']}")
    return " — ".join(parts)


def generate_response(
    question: str,
    relevant_chunks: List[Dict],
    scope: str = "all",
    selected_source: str = None,
) -> Dict:
    no_info_message = (
        "در سند انتخاب‌شده اطلاعات کافی برای پاسخ وجود ندارد."
        if scope == "selected"
        else "اطلاعات کافی در اسناد موجود برای پاسخ به این سؤال وجود ندارد."
    )

    if not relevant_chunks:
        return {"answer": no_info_message, "sources": []}

    try:
        context = "\n\n".join(
            f"[منبع: {_citation_label(c)}]\n{c['text']}" for c in relevant_chunks
        )

        scope_instruction = (
            f"The user has restricted the scope to a single document: \"{selected_source}\". "
            "Only use context chunks from that document. Ignore any general knowledge you may "
            f"have about the topic. If the context is insufficient, reply with exactly this "
            f"sentence and nothing else: \"{no_info_message}\""
            if scope == "selected"
            else
            f"If the context is insufficient, reply with exactly this sentence and nothing else: "
            f"\"{no_info_message}\""
        )

        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an assistant for question-answering tasks. Answer only based on "
                        "the retrieved context below. Do not add facts that are not present in the "
                        "retrieved context. You may use ordinary reading comprehension, such as "
                        "recognizing that a term in one passage and its translation/equivalent in "
                        "another retrieved passage refer to the same thing, but do not introduce "
                        "any claim that is not directly supported by the retrieved context. "
                        + scope_instruction + " "
                        "Always answer in the same language as the question. Keep the answer to "
                        "three sentences maximum."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            options={"temperature": 0.0, "num_ctx": 4096},
        )
        answer = response["message"]["content"].strip()
        if answer == no_info_message:
            sources = []
        else:
            sources = [_citation_label(c) for c in relevant_chunks]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        print(f"Error generating response: {str(e)}")
        return {"answer": "Error generating response.", "sources": []}