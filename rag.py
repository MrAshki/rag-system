import os
# Enforce fully-local model loading: never reach out to Hugging Face at runtime.
# (Everything is already on disk under models/; this guarantees no surprise download.)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import re
import json
import uuid
import torch
from dotenv import load_dotenv
import chromadb
from chromadb.utils import embedding_functions
import sys
import threading
from typing import Iterable, List, Dict, Optional

from document_pipeline import chunker
from model_gateway import get_chat_provider, list_chat_model_options
from model_gateway.base import ChatProvider

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
CHAT_PROVIDER = get_chat_provider()

# Bump this whenever the grounding/language prompt or guards change. It is logged
# at startup and on the health route so we can PROVE which prompt a running server
# is actually serving (a stale server keeps the old value in memory until restart).
ANSWER_PROMPT_VERSION = "rerank_v5"

# Two-stage retrieval: pull a wide dense net from Chroma (bge-m3), then rerank with a
# cross-encoder (bge-reranker-v2-m3) and keep the best few. The cross-encoder judges
# query/chunk relevance far better than dense similarity alone -- e.g. it ranks the
# book's actual thesis above a sub-argument the author only quotes to rebut.
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "./models/bge-reranker-v2-m3")
# CPU by default: the 8 GB GPU already holds bge-m3 and is shared with Ollama; reranking
# a few dozen short pairs on CPU takes a couple of seconds (latency is not a priority).
RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "true").strip().lower() == "true"
RETRIEVE_K = _positive_int_env("RETRIEVE_K", 30)   # wide dense net before reranking
RERANK_TOP_K = _positive_int_env("RERANK_TOP_K", 5)  # chunks kept for the answer

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

# Serializes access to the Chroma collection (which embeds via bge-m3 under the
# hood). The background scan worker indexes chunks on one thread while user
# queries embed on request threads; a single lock keeps embedding/Chroma calls
# from overlapping. Held only around individual collection calls (per-chunk on
# the index path), so queries can still interleave between a document's chunks.
_chroma_lock = threading.Lock()

# Startup banner so a running server proves which code/prompt it loaded.
print(
    f"[rag] loaded module={os.path.abspath(__file__)} "
    f"ANSWER_PROMPT_VERSION={ANSWER_PROMPT_VERSION} "
    f"CHAT_PROVIDER={CHAT_PROVIDER.name} CHAT_MODEL={CHAT_PROVIDER.model} "
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
        with _chroma_lock:
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
        with _chroma_lock:
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
    with _chroma_lock:
        data = collection.get(where=where, include=["metadatas"])
    seen = {}
    for m in data["metadatas"]:
        if m and m.get("document_id") and m["document_id"] not in seen:
            seen[m["document_id"]] = m.get("source", "نامشخص")
    return [
        {"document_id": doc_id, "source": source}
        for doc_id, source in sorted(seen.items(), key=lambda kv: kv[1])
    ]


def chat_model_options() -> List[Dict]:
    return list_chat_model_options()


def understand_query(text: str, chat_provider: ChatProvider = None) -> List[Dict]:
    """Interpret a (possibly messy, misspelled, mis-punctuated, or multi-part) user
    message into one or more distinct questions, each with a cleaned-up retrieval query.

    This replaces the old punctuation-based split_questions(): a real user may pack
    several questions into one message using periods instead of '؟', or write one long
    request that should stay a single question (e.g. "...چیه؟ مفصل توضیح بده"). The local
    model decides how many real questions there are and produces a focused search query
    for each (fixing spelling, expanding colloquialisms like 'راجب'->'راجع به', dropping
    filler/instruction words, and steering off ambiguous person-names toward the topic).

    Returns a list of {"user_question": str, "search_query": str}. SAFE FALLBACK: on any
    error or unusable output, returns the raw text as a single question so the pipeline
    never breaks."""
    text = (text or "").strip()
    fallback = [{"user_question": text, "search_query": text}]
    if not text:
        return fallback

    instruction = (
        "You analyze a user's message sent to a document question-answering system. "
        "The message may contain ONE or SEVERAL distinct questions, even if the user "
        "uses periods instead of question marks, writes informally, or has spelling "
        "mistakes. Your job is ONLY to understand and restructure the request -- never "
        "to answer it.\n\n"
        "Rules:\n"
        "- Identify each genuinely distinct question. Do NOT split a single question "
        "from its modifiers: phrases like 'مفصل توضیح بده' / 'explain in detail' / "
        "'به طور خلاصه' are part of the same question, not a new one.\n"
        "- Do NOT invent questions that were not asked.\n"
        "- For each question, write a concise SEARCH QUERY in the SAME language as that "
        "question (do not translate it): correct obvious spelling, expand colloquialisms, "
        "and drop filler/instruction words.\n"
        "- Anchor the search query on the TOPIC and key concepts, NOT on a person's bare "
        "name. A bare name can match the wrong person, and the document often discusses a "
        "view without naming who holds it. So for 'X's view on free will' / "
        "'نظر X درباره اراده آزاد', search for the topic itself (e.g. 'وجود اراده آزاد؛ "
        "استدلال کتاب') rather than the name X.\n\n"
        "Return ONLY valid JSON: "
        '{"questions": [{"user_question": "...", "search_query": "..."}]}'
    )
    try:
        provider = chat_provider or CHAT_PROVIDER
        content = provider.chat(
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ],
            options={"temperature": 0.0, "num_ctx": OLLAMA_NUM_CTX},
            response_format="json",
        )
        data = json.loads(content)
        cleaned = []
        for q in (data.get("questions") or [])[:10]:
            uq = (q.get("user_question") or "").strip()
            sq = (q.get("search_query") or "").strip()
            uq, sq = uq or sq, sq or uq
            if uq:
                cleaned.append({"user_question": uq, "search_query": sq})
        return cleaned or fallback
    except Exception as e:
        print(f"understand_query: falling back to raw text ({e})", flush=True)
        return fallback


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

        with _chroma_lock:
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


_reranker = None
_reranker_failed = False


def _get_reranker():
    """Lazily load the cross-encoder reranker once, on first use. Returns the model or
    None if it can't be loaded (in which case we silently fall back to dense ranking)."""
    global _reranker, _reranker_failed
    if _reranker is not None or _reranker_failed:
        return _reranker
    try:
        from sentence_transformers import CrossEncoder
        print(f"[rag] loading reranker {RERANKER_MODEL} on {RERANKER_DEVICE} ...", flush=True)
        _reranker = CrossEncoder(RERANKER_MODEL, device=RERANKER_DEVICE, max_length=512)
        print("[rag] reranker ready", flush=True)
    except Exception as e:
        _reranker_failed = True
        print(f"[rag] reranker unavailable, falling back to dense ranking ({e})", flush=True)
    return _reranker


def rerank(query: str, chunks: List[Dict], top_k: int) -> List[Dict]:
    """Reorder `chunks` by cross-encoder relevance to `query` and keep the best top_k.
    Safe fallback: if the reranker is disabled/unavailable or errors, returns the first
    top_k chunks unchanged (i.e. the dense order)."""
    if not chunks:
        return []
    if not ENABLE_RERANKER:
        return chunks[:top_k]
    model = _get_reranker()
    if model is None:
        return chunks[:top_k]
    try:
        scores = model.predict([(query, c["text"]) for c in chunks])
        ranked = sorted(zip(chunks, scores), key=lambda cs: float(cs[1]), reverse=True)
        return [c for c, _ in ranked[:top_k]]
    except Exception as e:
        print(f"rerank: falling back to dense order ({e})", flush=True)
        return chunks[:top_k]


def retrieve(query: str, document_id: str = None, user_id: int = None,
             top_k: int = None) -> List[Dict]:
    """Two-stage retrieval used by the answer pipeline: dense wide net -> cross-encoder
    rerank -> top_k. With reranking disabled this degrades to plain dense top_k."""
    top_k = top_k or RERANK_TOP_K
    wide = query_documents(query, n_results=RETRIEVE_K, document_id=document_id, user_id=user_id)
    return rerank(query, wide, top_k)


def _clean_heading(value) -> Optional[str]:
    """Keep only values that look like a real heading. Drops the junk this book's
    conversion produced: the placeholder "[]" chapter, and body paragraphs that the
    ingest step mis-detected as headings (a real heading is short and is not a full
    sentence/paragraph). A proper fix lives in the ingest/chunker preprocessing; this
    just stops the bad values from reaching the citation shown to the user."""
    if not value:
        return None
    v = str(value).strip()
    if not v or v == "[]":
        return None
    # Mis-detected paragraph-as-heading: too long, or ends like a sentence.
    if len(v) > 80 or v.rstrip().endswith((".", "؟", "!", "[1]")):
        return None
    return v


def _citation_label(chunk: Dict) -> str:
    """Builds a citation: filename — <best real heading> — p.N — chunk N.

    For this corpus `chapter` is the junk "[]" placeholder and `section` is often a
    mis-detected paragraph, while `subsection` holds the real nearby heading. So we
    cite the most specific *trustworthy* heading available (subsection, then section,
    then chapter), after filtering junk. Page is included only when present."""
    parts = [chunk["source"]]
    heading = (
        _clean_heading(chunk.get("subsection"))
        or _clean_heading(chunk.get("section"))
        or _clean_heading(chunk.get("chapter"))
    )
    if heading:
        parts.append(heading)
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


def _no_info_message(scope: str) -> str:
    return (
        "در سند انتخاب‌شده اطلاعات کافی برای پاسخ وجود ندارد."
        if scope == "selected"
        else "اطلاعات کافی در اسناد موجود برای پاسخ به این سؤال وجود ندارد."
    )


def _build_answer_messages(
    question: str,
    relevant_chunks: List[Dict],
    scope: str = "all",
    selected_source: str = None,
) -> List[Dict]:
    no_info_message = _no_info_message(scope)
    context = "\n\n".join(
        f"[S{i}: {_citation_label(c)}]\n{c['text']}"
        for i, c in enumerate(relevant_chunks, start=1)
    )

    lang = _question_language(question)
    if lang == "fa":
        language_directive = (
            "زبان سؤال کاربر فارسی است. کل پاسخ را فقط و فقط به فارسیِ روان و طبیعی "
            "بنویس، حتی اگر متنِ بازیابی‌شده انگلیسی باشد."
        )
        lang_reminder = "یادآوری: پاسخ را فقط به فارسیِ روان بنویس."
    else:
        language_directive = (
            "The user's question is in English. Write your entire answer in fluent "
            "English, even if the retrieved context is in another language."
        )
        lang_reminder = "Reminder: answer in English."

    scope_instruction = (
        f"The user restricted the scope to a single document: \"{selected_source}\". "
        "Use only context from that document. "
        if scope == "selected"
        else ""
    )

    # One short, principled prompt. No rule cascades, no entity regex, no
    # placeholder templates -- those made answers worse (see plan/). The model is
    # trusted to apply clear principles; grounding stays strict because the answer
    # may only use the verbatim retrieved context below.
    system_content = (
        "You are a knowledgeable assistant answering questions about the user's "
        "documents, using only the retrieved context provided below.\n\n"
        "ANSWER LANGUAGE (most important): " + language_directive + " The answer "
        "language is decided only by the question, never by the language of the context.\n\n"
        "GROUNDING: Use only what is actually in the retrieved context. Do not use "
        "outside or general knowledge, and do not invent facts. You may use ordinary "
        "reading comprehension (e.g. recognizing that a term and its translation mean the "
        "same thing).\n\n"
        "IF the retrieved context does not contain enough to answer, reply with exactly "
        "this sentence and nothing else: \"" + no_info_message + "\"\n\n"
        "NAMED-PERSON CHECK (very important): The retrieved context is selected by topic "
        "and may NOT mention the specific person named in the question. Before you write "
        "\"<name> believes/says/argues ...\" or otherwise attribute any view to a named "
        "person, first check whether that person's actual name literally appears in the "
        "retrieved context. Do NOT assume the person named in the question is the author "
        "of the document or anyone mentioned in it -- a name only counts as present if it "
        "literally appears in the retrieved context above. If the name does NOT appear "
        "there, you must NOT attribute anything to them, must NOT call them the author, "
        "and must NOT put their name in your answer as a view-holder. Instead, briefly "
        "note that the text does not specifically discuss that person, then answer about "
        "the topic itself from the context. Only attribute a view to a person whose name "
        "actually appears in the retrieved context.\n"
        "Worked example: if the question is «نظر فلانی درباره اراده آزاد چیه؟» and the "
        "name «فلانی» does not literally appear in the context (even though the context "
        "talks about 'the author' or says 'I'), the correct answer begins with something "
        "like «در متن بازیابی‌شده به‌طور خاص دربارهٔ فلانی چیزی نیامده است» and then "
        "summarizes the topic. It must NOT say «فلانی نویسنده است» or «فلانی معتقد است ...». "
        "On the other hand, if the asked name (or an obvious equivalent) DOES literally "
        "appear in the retrieved context, just answer normally and attribute to them -- do "
        "NOT add any 'not discussed' note in that case.\n\n"
        "STYLE: Answer directly, naturally, and fluently, like a knowledgeable person "
        "explaining clearly. Match the depth to the question -- keep simple questions "
        "concise, and when the user asks for explanation or detail, give a fuller, "
        "well-organized answer. Do not be creative or speculative. " + scope_instruction +
        "\n\n"
        "CITATIONS: Every factual sentence or bullet that uses the retrieved context MUST "
        "end with one or more source markers like [S1] or [S2][S4]. Use the S-number from "
        "the context block that supports that exact claim. Do not put citations in a final "
        "references section. Do not write a separate sources list. If a sentence combines "
        "facts from multiple chunks, cite all relevant chunks at the end of that sentence."
    ).strip()

    user_content = f"Context:\n{context}\n\nQuestion: {question}\n\n{lang_reminder}"
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def _sources_for_answer(answer: str, no_info_message: str, chunks: List[Dict]) -> List[str]:
    return [] if answer == no_info_message else [_citation_label(c) for c in chunks]


def generate_response(
    question: str,
    relevant_chunks: List[Dict],
    scope: str = "all",
    selected_source: str = None,
    chat_provider: ChatProvider = None,
) -> Dict:
    no_info_message = _no_info_message(scope)
    if not relevant_chunks:
        return {"answer": no_info_message, "sources": []}

    try:
        provider = chat_provider or CHAT_PROVIDER
        answer = provider.chat(
            messages=_build_answer_messages(
                question,
                relevant_chunks,
                scope=scope,
                selected_source=selected_source,
            ),
            options={"temperature": 0.0, "num_ctx": OLLAMA_NUM_CTX},
        ).strip()
        sources = _sources_for_answer(answer, no_info_message, relevant_chunks)
        return {"answer": answer, "sources": sources}
    except Exception as e:
        print(f"Error generating response: {str(e)}")
        return {"answer": "خطا در تولید پاسخ.", "sources": []}


def _trace(stage: str, status: str, **data) -> Dict:
    event = {"type": "trace", "stage": stage, "status": status}
    event.update(data)
    return event


def generate_response_stream(
    question: str,
    relevant_chunks: List[Dict],
    scope: str = "all",
    selected_source: str = None,
    chat_provider: ChatProvider = None,
) -> Iterable[Dict]:
    no_info_message = _no_info_message(scope)
    if not relevant_chunks:
        yield {"type": "token", "delta": no_info_message}
        yield {"type": "final", "answer": no_info_message, "sources": []}
        return

    try:
        provider = chat_provider or CHAT_PROVIDER
        answer_parts = []
        for delta in provider.stream_chat(
            messages=_build_answer_messages(
                question,
                relevant_chunks,
                scope=scope,
                selected_source=selected_source,
            ),
            options={"temperature": 0.0, "num_ctx": OLLAMA_NUM_CTX},
        ):
            answer_parts.append(delta)
            yield {"type": "token", "delta": delta}

        answer = "".join(answer_parts).strip()
        sources = _sources_for_answer(answer, no_info_message, relevant_chunks)
        yield {"type": "final", "answer": answer, "sources": sources}
    except Exception as e:
        print(f"Error streaming response: {str(e)}")
        yield {"type": "error", "error": "خطا در تولید پاسخ."}


def answer_request(
    question: str,
    scope: str = "all",
    document_id: str = None,
    user_id: int = None,
    selected_source: str = None,
    chat_provider_name: str = None,
    chat_model: str = None,
) -> Dict:
    """End-to-end answer pipeline used by the app:
        understand the message -> for each distinct question, retrieve its own context
    and answer it grounded -> assemble.

    A single question returns a single clean answer (same shape as generate_response).
    Several questions return one organized response that addresses each in turn, each
    grounded only in its own retrieved context (so questions never cross-contaminate
    and the context window never has to hold everything at once)."""
    doc_filter = document_id if scope == "selected" else None
    provider = get_chat_provider(chat_provider_name, chat_model)
    sub_qs = understand_query(question, chat_provider=provider)

    if len(sub_qs) == 1:
        sq = sub_qs[0]
        chunks = retrieve(sq["search_query"], document_id=doc_filter, user_id=user_id)
        return generate_response(
            sq["user_question"],
            chunks,
            scope=scope,
            selected_source=selected_source,
            chat_provider=provider,
        )

    blocks = []
    merged_sources = []
    seen = set()
    for sq in sub_qs:
        chunks = retrieve(sq["search_query"], document_id=doc_filter, user_id=user_id)
        sub = generate_response(
            sq["user_question"],
            chunks,
            scope=scope,
            selected_source=selected_source,
            chat_provider=provider,
        )
        blocks.append(f"❖ {sq['user_question']}\n{sub['answer']}")
        for s in sub["sources"]:
            if s not in seen:
                seen.add(s)
                merged_sources.append(s)
    return {"answer": "\n\n".join(blocks), "sources": merged_sources}


def answer_request_stream(
    question: str,
    scope: str = "all",
    document_id: str = None,
    user_id: int = None,
    selected_source: str = None,
    chat_provider_name: str = None,
    chat_model: str = None,
) -> Iterable[Dict]:
    """Streaming twin of answer_request.

    Yields JSON-serializable events:
      trace: pipeline progress
      token: answer text delta
      final: final answer + sources
      error: recoverable failure
      done: stream is complete
    """
    doc_filter = document_id if scope == "selected" else None
    provider = get_chat_provider(chat_provider_name, chat_model)
    yield _trace("request", "started")

    yield _trace("understand_query", "started")
    sub_qs = understand_query(question, chat_provider=provider)
    yield _trace("understand_query", "done", question_count=len(sub_qs))

    if len(sub_qs) == 1:
        sq = sub_qs[0]
        yield _trace("retrieve", "started", query=sq["search_query"])
        chunks = retrieve(sq["search_query"], document_id=doc_filter, user_id=user_id)
        yield _trace("retrieve", "done", chunks=len(chunks))

        yield _trace(
            "generate",
            "started",
            provider=provider.name,
            model=provider.model,
        )
        final_event = None
        for event in generate_response_stream(
            sq["user_question"],
            chunks,
            scope=scope,
            selected_source=selected_source,
            chat_provider=provider,
        ):
            if event.get("type") == "final":
                final_event = event
            else:
                yield event
        yield _trace("generate", "done")
        if final_event:
            yield final_event
        yield {"type": "done"}
        return

    answer_parts = []
    merged_sources = []
    seen = set()
    for i, sq in enumerate(sub_qs):
        yield _trace(
            "sub_question",
            "started",
            index=i + 1,
            total=len(sub_qs),
            question=sq["user_question"],
        )
        yield _trace("retrieve", "started", index=i + 1, query=sq["search_query"])
        chunks = retrieve(sq["search_query"], document_id=doc_filter, user_id=user_id)
        yield _trace("retrieve", "done", index=i + 1, chunks=len(chunks))

        separator = "\n\n" if i else ""
        prefix = f"{separator}❖ {sq['user_question']}\n"
        answer_parts.append(prefix)
        yield {"type": "token", "delta": prefix}

        yield _trace(
            "generate",
            "started",
            index=i + 1,
            provider=provider.name,
            model=provider.model,
        )
        final_event = None
        for event in generate_response_stream(
            sq["user_question"],
            chunks,
            scope=scope,
            selected_source=selected_source,
            chat_provider=provider,
        ):
            if event.get("type") == "final":
                final_event = event
                answer_parts.append(event.get("answer", ""))
                for source in event.get("sources", []):
                    if source not in seen:
                        seen.add(source)
                        merged_sources.append(source)
            elif event.get("type") == "token":
                yield event
            else:
                yield event
        yield _trace("generate", "done", index=i + 1)
        yield _trace("sub_question", "done", index=i + 1)

    yield {
        "type": "final",
        "answer": "".join(answer_parts),
        "sources": merged_sources,
    }
    yield {"type": "done"}
