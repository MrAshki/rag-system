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

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
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


def load_documents_from_directory(directory_path: str) -> List[Dict[str, str]]:
    if not os.path.exists(directory_path):
        print(f"Error: Directory {directory_path} does not exist")
        return []

    documents = []
    for filename in os.listdir(directory_path):
        if filename.endswith(".txt"):
            try:
                with open(os.path.join(directory_path, filename), "r", encoding="utf-8") as file:
                    documents.append({"id": filename, "text": file.read()})
            except Exception as e:
                print(f"Error reading {filename}: {str(e)}")
    return documents


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


def index_document(filename: str, text: str, document_id: Optional[str] = None) -> Dict:
    """Chunk a document and upsert it under a stable document_id, so two documents that
    happen to share a filename never collide or get mixed in the vector store."""
    document_id = document_id or uuid.uuid4().hex
    chunks = split_text(text)
    print(f"Indexing '{filename}' ({len(chunks)} chunks) on {EMBEDDING_DEVICE}...", flush=True)
    for i, chunk in enumerate(chunks):
        collection.upsert(
            ids=[f"{document_id}_chunk{i+1}"],
            documents=[chunk],
            metadatas=[{"document_id": document_id, "source": filename, "chunk": i + 1}],
        )
        if (i + 1) % 50 == 0 or (i + 1) == len(chunks):
            print(f"  {filename}: {i+1}/{len(chunks)} chunks indexed", flush=True)
    return {"document_id": document_id, "chunks": len(chunks)}


def list_documents() -> List[Dict]:
    """Return the distinct indexed documents as {document_id, source} for UI display."""
    data = collection.get(include=["metadatas"])
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


def query_documents(question: str, n_results: int = 5, document_id: str = None) -> List[Dict]:
    try:
        where = {"document_id": document_id} if document_id else None
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
            chunks.append({
                "text": doc,
                "source": (meta or {}).get("source", "نامشخص"),
                "chunk": (meta or {}).get("chunk", "?"),
            })
        return chunks
    except Exception as e:
        print(f"Error querying documents: {str(e)}")
        return []


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
            f"[منبع: {c['source']} - بخش {c['chunk']}]\n{c['text']}" for c in relevant_chunks
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
            sources = [f"{c['source']} — chunk {c['chunk']}" for c in relevant_chunks]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        print(f"Error generating response: {str(e)}")
        return {"answer": "Error generating response.", "sources": []}


def main():
    documents = load_documents_from_directory("./docs")
    if not documents:
        return

    for doc in documents:
        index_document(doc["id"], doc["text"])

    question = "what age range does it affect with cosmeticorexia?"
    relevant_chunks = query_documents(question)
    if relevant_chunks:
        result = generate_response(question, relevant_chunks)
        print("\nAnswer:", result["answer"])
        print("Sources:", ", ".join(result["sources"]))


if __name__ == "__main__":
    main()