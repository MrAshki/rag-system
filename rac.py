import os
from dotenv import load_dotenv
import chromadb
from chromadb.utils import embedding_functions
import ollama
import sys
from typing import List, Dict

load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
COLLECTION_NAME = "document_qa_collection_local"

CATEGORIES = [
    "physical_risk",       # skin damage, dermatological harm
    "psychological_risk",  # body image, self-esteem, anxiety
    "social_risk",         # peer pressure, social media influence
    "commercial",          # brands, marketing, influencers, money
    "not_related",         # unrelated to the document topics
]

try:
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
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


def query_documents(question: str, n_results: int = 5) -> List[str]:
    try:
        results = collection.query(query_texts=[question], n_results=n_results)
        return [doc for sublist in results["documents"] for doc in sublist]
    except Exception as e:
        print(f"Error querying documents: {str(e)}")
        return []


def classify(text: str, relevant_chunks: List[str]) -> dict:
    if not relevant_chunks:
        return {"category": "not_related", "reason": "No relevant context found."}

    try:
        context = "\n\n".join(relevant_chunks)
        categories_str = "\n".join(f"- {c}" for c in CATEGORIES)
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a classification assistant. "
                        "Using only the provided context from our documents, "
                        "classify the user input into exactly one of the following categories:\n"
                        f"{categories_str}\n\n"
                        "Respond in this exact format:\n"
                        "Category: <category_name>\n"
                        "Reason: <one sentence explanation based on the context>"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nClassify this text: {text}",
                },
            ],
            options={"temperature": 0.0, "num_ctx": 4096},
        )
        raw = response["message"]["content"].strip()
        category, reason = "not_related", raw
        for line in raw.splitlines():
            if line.lower().startswith("category:"):
                category = line.split(":", 1)[1].strip().lower()
            if line.lower().startswith("reason:"):
                reason = line.split(":", 1)[1].strip()
        return {"category": category, "reason": reason}
    except Exception as e:
        print(f"Error classifying: {str(e)}")
        return {"category": "error", "reason": str(e)}


def main():
    documents = load_documents_from_directory("./docs")
    if not documents:
        return

    chunked_documents = []
    for doc in documents:
        chunks = split_text(doc["text"])
        for i, chunk in enumerate(chunks):
            chunked_documents.append({"id": f"{doc['id']}_chunk{i+1}", "text": chunk})

    for doc in chunked_documents:
        try:
            collection.upsert(ids=[doc["id"]], documents=[doc["text"]])
        except Exception as e:
            print(f"Error upserting chunk {doc['id']}: {str(e)}")

    inputs = [
        "My 9-year-old is using retinol serum every day and now has a rash on her face.",
        "She refuses to go to school without a full makeup routine and cries if she can't do it.",
        "Drunk Elephant and Bubble are being promoted by kids on TikTok to their followers.",
        "The weather in Amsterdam is nice today.",
    ]

    for text in inputs:
        chunks = query_documents(text)
        result = classify(text, chunks)
        print(f"\nInput:    {text}")
        print(f"Category: {result['category']}")
        print(f"Reason:   {result['reason']}")
        print("-" * 70)


if __name__ == "__main__":
    main()