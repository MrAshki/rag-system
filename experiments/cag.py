import os
import ollama
from dotenv import load_dotenv

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
DOCS_DIR = "./docs"


def load_documents(directory: str) -> str:
    context = ""
    for filename in sorted(os.listdir(directory)):
        if filename.endswith(".txt"):
            with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
                context += f.read() + "\n\n"
    return context.strip()


def generate_response(question: str, context: str) -> str:
    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an assistant for question-answering tasks. Use only the provided "
                    "context to answer the question. If the answer is not in the context, say so "
                    "clearly instead of guessing. Always answer in the same language as the "
                    "question. Keep the answer to three sentences maximum."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
        options={"temperature": 0.0, "num_ctx": 8192},
    )
    return response["message"]["content"].strip()


def main():
    context = load_documents(DOCS_DIR)
    print(f"Context loaded: ~{len(context) // 4} tokens\n")

    question = "What is cosmeticorexia, what age group does it affect, and what are the physical skin risks identified by dermatologists?"
    answer = generate_response(question, context)
    print("Answer:", answer)


if __name__ == "__main__":
    main()