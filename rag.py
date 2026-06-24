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

from document_pipeline import chunker

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


def _positive_int_env(name: str, default: int) -> int:
    """Reads an integer env var, falling back to `default` if unset/blank.
    Fails fast (rather than silently using a wrong context size) if the value
    is present but not a positive integer -- e.g. a typo'd OLLAMA_NUM_CTX could
    otherwise silently truncate context without any visible error."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer (got {raw!r}). Fix .env.")
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer (got {value}). Fix .env.")
    return value


EMBEDDING_MODEL = _require_env("EMBEDDING_MODEL")
OLLAMA_MODEL = _require_env("OLLAMA_MODEL")
OLLAMA_NUM_CTX = _positive_int_env("OLLAMA_NUM_CTX", 4096)
COLLECTION_NAME = "document_qa_collection_local"

# Bump this whenever the grounding/language prompt or guards change. It is logged
# at startup and on the health route so we can PROVE which prompt a running server
# is actually serving (a stale server keeps the old value in memory until restart).
ANSWER_PROMPT_VERSION = "grounding_v2"

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

# Startup banner so a running server proves which code/prompt it loaded.
print(
    f"[rag] loaded module={os.path.abspath(__file__)} "
    f"ANSWER_PROMPT_VERSION={ANSWER_PROMPT_VERSION} "
    f"OLLAMA_MODEL={OLLAMA_MODEL} OLLAMA_NUM_CTX={OLLAMA_NUM_CTX} "
    f"EMBEDDING_MODEL={EMBEDDING_MODEL}",
    flush=True,
)


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


def _question_language(text: str) -> str:
    """Decide the answer language from the *question itself*, never from the
    retrieved context. Any Persian/Arabic-script character -> 'fa', otherwise 'en'.
    This is the fix that stops an English source document from dragging a Persian
    question's answer into English."""
    if re.search(r"[؀-ۿ]", text or ""):
        return "fa"
    return "en"


def _text_language(text: str) -> str:
    """Majority-script of an arbitrary text (used to audit the *model's answer*,
    not the question). Returns 'fa', 'en', or 'unknown'."""
    fa = len(re.findall(r"[؀-ۿ]", text or ""))
    en = len(re.findall(r"[A-Za-z]", text or ""))
    if fa == 0 and en == 0:
        return "unknown"
    return "fa" if fa >= en else "en"


# Patterns that mean "the view/opinion of <NAME>" — used only to GUARD against
# attributing a stance to someone absent from the retrieved context.
_ENTITY_PATTERNS = [
    r"از\s*نظر\s+(.+?)(?:\s+(?:چیه|چیست|چی|چطور|درباره|راجع|در\s*مورد|است|هست)\b|[،؟?]|$)",
    r"از\s*دیدگاه\s+(.+?)(?:\s+(?:چیه|چیست|چی|درباره|راجع|در\s*مورد)\b|[،؟?]|$)",
    r"\bنظر\s+(.+?)\s+(?:درباره|راجع\s*به|در\s*مورد)\b",
    r"به\s*گفته[ٔ‌ ]?\s*(.+?)(?:[،؟?]|\s+(?:درباره|در\s*مورد)\b|$)",
    r"according to\s+([A-Za-z.''\- ]+?)(?:\s+(?:about|on|regarding)\b|[,?.]|$)",
    r"what does\s+([A-Za-z.''\- ]+?)\s+(?:say|think|argue|believe|claim)\b",
    r"([A-Z][A-Za-z.''\-]+(?:\s+[A-Z][A-Za-z.''\-]+)*)'s\s+(?:view|opinion|take|argument|position)\b",
]

_DISCLAIMER_MARKERS = [
    "پیدا نکردم", "اشاره‌ای به", "اشاره ای به", "یافت نشد", "ذکر نشده", "نشده است",
    "not found", "couldn't find", "could not find", "couldn’t find",
    "does not mention", "doesn't mention", "no mention",
]


def _extract_asked_entity(question: str):
    """Heuristic: if the question asks for the view/opinion of a specific named
    person ('از نظر محمد اشکریز...', 'according to X...'), return that name; else
    None. This never adds content — it only decides whether to RUN the guard."""
    for pat in _ENTITY_PATTERNS:
        m = re.search(pat, question or "", flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip(" \t.،؟?\"'")
            # drop trivial/topic-like captures
            if name and len(name) >= 2 and name.lower() not in ("the book", "it", "این کتاب", "کتاب"):
                return name
    return None


def _entity_in_text(entity: str, text: str) -> bool:
    """Whether a named entity is actually present in the retrieved text. Matches the
    full name, or its distinctive last token (surname), case-insensitively."""
    e = (entity or "").strip().lower()
    t = (text or "").lower()
    if not e:
        return False
    if e in t:
        return True
    tokens = [tok for tok in re.split(r"\s+", e) if len(tok) >= 3]
    if not tokens:
        return False
    return tokens[-1] in t


def _has_disclaimer(answer: str) -> bool:
    return any(m in (answer or "") for m in _DISCLAIMER_MARKERS)


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

        lang = _question_language(question)
        if lang == "fa":
            language_directive = (
                "زبان سؤال کاربر فارسی است. کل پاسخ را فقط و فقط به فارسیِ روان و طبیعی "
                "بنویس، حتی اگر متنِ بازیابی‌شده انگلیسی باشد. به هیچ زبان دیگری پاسخ نده."
            )
            entity_template_hint = (
                "برای پاسخِ فارسی دقیقاً از همین قالب استفاده کن و جای‌نگه‌دارها را پر کن: "
                "«در بخش‌های بازیابی‌شده، اشاره‌ای به [نام موجودیت] پیدا نکردم؛ اما متن "
                "درباره [موضوع] چنین می‌گوید: ...»."
            )
        else:
            language_directive = (
                "The user's question is in English. Write your entire answer in English, "
                "even if the retrieved context is in another language."
            )
            entity_template_hint = (
                "For an English answer use this shape, filling in the placeholders: "
                "\"I couldn't find any mention of [entity] in the retrieved passages, but "
                "the text does say the following about [topic]: ...\"."
            )

        scope_instruction = (
            f"The user has restricted the scope to a single document: \"{selected_source}\". "
            "Only use context chunks from that document. Ignore any general knowledge you may "
            "have about the topic. "
            if scope == "selected"
            else ""
        )

        system_content = (
            "You are a careful, grounded question-answering assistant. Answer ONLY from the "
            "retrieved context provided below.\n\n"
            "ANSWER LANGUAGE (highest priority): " + language_directive + " The answer "
            "language is decided solely by the language of the question, never by the "
            "language of the retrieved context.\n\n"
            "GROUNDING: Use only information that is actually present in the retrieved "
            "context. Do not use outside/general knowledge and do not invent facts. You may "
            "use basic reading comprehension (for example, recognizing that a term and its "
            "translation refer to the same thing), but never introduce a claim that is not "
            "supported by the retrieved context. Never attribute a view or statement to a "
            "person who is not actually named in the retrieved context.\n\n"
            "DECISION PROCEDURE (apply in order, then stop):\n"
            "1) If the retrieved context does not address the question at all, reply with "
            "exactly this sentence and nothing else: \"" + no_info_message + "\"\n"
            "2) Otherwise, check whether the QUESTION ITSELF names a specific person, author, "
            "or work. Only if it does AND that exact name (or an obvious equivalent) is NOT "
            "present in the retrieved context: begin by stating that this name was not found, "
            "then give the grounded information about the general topic instead. Do not "
            "attribute any view to the missing person. " + entity_template_hint + "\n"
            "3) In EVERY OTHER case, simply answer the question directly and naturally from "
            "the context. Do NOT add any preamble about whether a name or entity is or isn't "
            "mentioned, and never invent a name just to say it was not found. The disclaimer "
            "in step 2 is allowed ONLY when the user's own question contained a specific "
            "personal name that is missing from the context. For example, for a general "
            "question such as \"what does the book say about X?\" / «کتاب درباره X چه می‌گوید؟», "
            "answer directly about X and do NOT include any sentence about a name not being "
            "found.\n\n"
            "STYLE: Be natural, clear, and useful, and match the depth of the answer to the "
            "question. Do not be creative, loose, or speculative. " + scope_instruction
        ).strip()

        lang_reminder = (
            "یادآوری: پاسخ را فقط به فارسی بنویس."
            if lang == "fa"
            else "Reminder: write the answer in English."
        )

        user_content = f"Context:\n{context}\n\nQuestion: {question}\n\n{lang_reminder}"

        def _chat(system: str) -> str:
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                options={"temperature": 0.0, "num_ctx": OLLAMA_NUM_CTX},
            )
            return resp["message"]["content"].strip()

        answer = _chat(system_content)

        # --- Deterministic guard 1: never attribute a view to a named person who is
        # absent from the retrieved context. Triggers ONLY when the question asks for
        # a specific person's view AND that name is not in the context AND the model
        # did not already disclaim. The fix is a forced regeneration (still grounded in
        # the same chunks) -- it invents no content. ----------------------------------
        asked_entity = _extract_asked_entity(question)
        if asked_entity and not _entity_in_text(asked_entity, context) and not _has_disclaimer(answer):
            forced = system_content + (
                f"\n\nCRITICAL OVERRIDE: The name \"{asked_entity}\" does NOT appear anywhere "
                f"in the retrieved context above. You must NOT attribute any view, opinion, or "
                f"statement to \"{asked_entity}\". Begin your answer by clearly stating that "
                f"\"{asked_entity}\" was not found in the retrieved text, then explain ONLY the "
                f"grounded general topic from the context."
            )
            answer = _chat(forced)

        # --- Deterministic guard 2: a Persian question must get a Persian answer, even
        # if the retrieved context is English. Regenerate once if the model slipped. ---
        if lang == "fa" and _text_language(answer) == "en":
            forced_lang = system_content + (
                "\n\nCRITICAL OVERRIDE: Write the ENTIRE answer in fluent Persian (فارسی) only. "
                "Do not output any English sentences."
            )
            answer = _chat(forced_lang)

        if answer == no_info_message:
            sources = []
        else:
            sources = [_citation_label(c) for c in relevant_chunks]
        return {"answer": answer, "sources": sources}
    except Exception as e:
        print(f"Error generating response: {str(e)}")
        return {"answer": "Error generating response.", "sources": []}