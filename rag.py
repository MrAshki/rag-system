import os
# Enforce fully-local model loading: never reach out to Hugging Face at runtime.
# (Everything is already on disk under models/; this guarantees no surprise download.)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import re
import json
import uuid
import time
from dotenv import load_dotenv
import sys
from typing import Iterable, List, Dict, Optional

from document_pipeline import chunker
from backend.app.core.config import settings
from backend.app.vector import get_vector_store
from backend.app.vector.base import VectorChunk
from backend.app.vector.embeddings import embed_text, embedding_device
from backend.app.vector.rerankers import openrouter_rerank, reranker_provider
from backend.app.retrieval import hybrid_search_stages, retrieve_r2
from backend.app.grounding import (
    build_grounded_messages,
    grounded_contract_error,
    parse_grounded_response,
    repair_grounded_contract,
)
from backend.app.generation import GenerationPayload, GenerationUnavailableError, GroundedGenerationOrchestrator
from backend.app.services.usage_tracking import estimate_tokens_from_text, record_compute_usage_event
from model_gateway import get_chat_provider, list_chat_model_options
from model_gateway.base import ChatProvider

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(override=True, encoding="utf-8-sig")

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


EMBEDDING_MODEL = settings.embedding_model
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or os.getenv("CHAT_MODEL") or ""
OLLAMA_NUM_CTX = _positive_int_env("OLLAMA_NUM_CTX", 4096)
CHAT_PROVIDER = get_chat_provider("openrouter", settings.rag_primary_generator_model)

# Bump this whenever the grounding/language prompt or guards change. It is logged
# at startup and on the health route so we can PROVE which prompt a running server
# is actually serving (a stale server keeps the old value in memory until restart).
ANSWER_PROMPT_VERSION = "structured_citations_v5_metric_optimization"

# R2 fuses bounded lexical and Nemotron dense candidates, then reranks exactly once.
RERANKER_PROVIDER = reranker_provider()
RERANKER_MODEL = os.getenv(
    "RERANKER_MODEL",
    "nvidia/llama-nemotron-rerank-vl-1b-v2:free" if RERANKER_PROVIDER == "openrouter" else "./models/bge-reranker-v2-m3",
)
# Local reranking remains a generic gateway capability; production uses OpenRouter.
RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
ENABLE_RERANKER = os.getenv("ENABLE_RERANKER", "true").strip().lower() == "true"
RETRIEVE_K = _positive_int_env("RETRIEVE_K", 30)   # wide dense net before reranking
RERANK_TOP_K = _positive_int_env("RERANK_TOP_K", 5)  # chunks kept for the answer
ENABLE_LANGGRAPH_RAG = os.getenv("ENABLE_LANGGRAPH_RAG", "true").strip().lower() == "true"
ENABLE_HYBRID_RETRIEVAL = os.getenv("ENABLE_HYBRID_RETRIEVAL", "true").strip().lower() == "true"
LEXICAL_SCAN_LIMIT = _positive_int_env("LEXICAL_SCAN_LIMIT", 2000)
RETRIEVAL_MODE = settings.rag_retrieval_mode
CROSS_LANGUAGE_REWRITE_ENABLED = settings.rag_cross_language_rewrite_enabled
PRIMARY_GENERATOR_MODEL = settings.rag_primary_generator_model
FALLBACK_GENERATOR_MODEL = settings.rag_fallback_generator_model
GENERATOR_FALLBACK_ENABLED = settings.rag_generator_fallback_enabled

EMBEDDING_DEVICE = embedding_device()
if EMBEDDING_DEVICE == "cuda":
    try:
        import torch

        device_name = torch.cuda.get_device_name(0)
    except Exception:
        device_name = "unknown"
    print(f"Embedding device: cuda - {device_name}")
else:
    print(f"Embedding device: {EMBEDDING_DEVICE}")

vector_store = get_vector_store()

# Startup banner so a running server proves which code/prompt it loaded.
print(
    f"[rag] loaded module={os.path.abspath(__file__)} "
    f"ANSWER_PROMPT_VERSION={ANSWER_PROMPT_VERSION} "
    f"CHAT_PROVIDER={CHAT_PROVIDER.name} CHAT_MODEL={CHAT_PROVIDER.model} "
    f"OLLAMA_MODEL={OLLAMA_MODEL or 'disabled'} OLLAMA_NUM_CTX={OLLAMA_NUM_CTX} "
    f"EMBEDDING_PROVIDER={settings.embedding_provider} EMBEDDING_MODEL={EMBEDDING_MODEL} "
    f"VECTOR_BACKEND={settings.vector_backend} RETRIEVAL_MODE={RETRIEVAL_MODE} "
    f"PRIMARY_GENERATOR={PRIMARY_GENERATOR_MODEL} FALLBACK_GENERATOR={FALLBACK_GENERATOR_MODEL} "
    f"ENABLE_LANGGRAPH_RAG={ENABLE_LANGGRAPH_RAG}",
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
    vector_chunks = [
        VectorChunk(
            chunk_id=f"{document_id}_chunk{i + 1}",
            user_id=user_id,
            document_id=document_id,
            source=filename,
            chunk_index=i + 1,
            text=chunk,
            metadata={
                "document_id": document_id,
                "source": filename,
                "chunk": i + 1,
                "user_id": user_id,
            },
        )
        for i, chunk in enumerate(chunks)
    ]
    vector_store.add_chunks(vector_chunks)
    if chunks:
        print(f"  {filename}: {len(chunks)}/{len(chunks)} chunks indexed", flush=True)
    return {"document_id": document_id, "chunks": len(chunks)}


def index_chunks(
    filename: str,
    chunks: List[Dict],
    document_id: Optional[str] = None,
    user_id: int = None,
    source_file_type: str = None,
    normalized_md_path: str = None,
    document_language: str = None,
) -> Dict:
    """Index pre-built structure-aware chunks (from chunker.parse_markdown_to_chunks)
    under a stable document_id. Each chunk's stored/embedded text gets the short
    contextual header (chapter/section/page) prepended via chunker.build_embedded_text,
    and the same fields are kept as queryable metadata."""
    document_id = document_id or uuid.uuid4().hex
    print(f"Indexing '{filename}' ({len(chunks)} structured chunks) on {EMBEDDING_DEVICE} for user_id={user_id}...", flush=True)
    vector_chunks = []
    for i, ch in enumerate(chunks):
        metadata = {
            "document_id": document_id,
            "source": filename,
            "chunk": ch["chunk_index"],
            "user_id": user_id,
            "source_file_type": source_file_type,
            "normalized_md_path": normalized_md_path,
            "document_language": document_language,
            "chapter": ch.get("chapter"),
            "section": ch.get("section"),
            "subsection": ch.get("subsection"),
            "page": ch.get("page"),
            "char_start": ch.get("char_start"),
            "char_end": ch.get("char_end"),
            "parent_id": ch.get("parent_id"),
            "parent_title": ch.get("parent_title"),
            "parent_type": ch.get("parent_type"),
            "parent_role": ch.get("parent_role"),
            "parent_page_start": ch.get("parent_page_start"),
            "parent_page_end": ch.get("parent_page_end"),
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        vector_chunks.append(
            VectorChunk(
                chunk_id=f"{document_id}_chunk{ch['chunk_index']}",
                user_id=user_id,
                document_id=document_id,
                source=filename,
                chunk_index=ch["chunk_index"],
                text=chunker.build_embedded_text(ch),
                metadata=metadata,
            )
        )
        if (i + 1) % 50 == 0 or (i + 1) == len(chunks):
            print(f"  {filename}: {i+1}/{len(chunks)} chunks prepared", flush=True)
    vector_store.add_chunks(vector_chunks)
    if chunks:
        print(f"  {filename}: {len(chunks)}/{len(chunks)} chunks indexed", flush=True)
    return {"document_id": document_id, "chunks": len(chunks)}


def list_documents(user_id: int = None) -> List[Dict]:
    """Return scanned documents for UI display, independent of vector backend."""
    from sqlalchemy import text
    from backend.app.db.session import session_scope

    params = {}
    where = ""
    if user_id is not None:
        where = "WHERE user_id = :user_id"
        params["user_id"] = user_id
    status_clause = "AND" if where else "WHERE"
    with session_scope() as session:
        rows = session.execute(
            text(
                f"""
                SELECT id AS document_id, original_filename AS source
                  FROM assets
                  {where}
                 {status_clause} category = 'text'
                   AND status = 'scanned'
                 ORDER BY original_filename
                """
            ),
            params,
        ).mappings().all()
    return [
        {"document_id": row["document_id"], "source": row["source"] or "نامشخص"}
        for row in rows
    ]


def chat_model_options() -> List[Dict]:
    return list_chat_model_options()


def indexed_chunk_count() -> int:
    return vector_store.count()


def delete_document_index(document_id: str, user_id: int = None) -> int:
    return vector_store.delete_document(document_id, user_id=user_id)


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


def query_documents(
    question: str,
    n_results: int = 5,
    document_id: str = None,
    document_ids: List[str] = None,
    user_id: int = None,
    stage_recorder=None,
    search_label: str = "original",
) -> List[Dict]:
    try:
        filters = {}
        if user_id is not None:
            filters["user_id"] = user_id
        document_ids = [doc_id for doc_id in (document_ids or []) if doc_id]
        if document_ids:
            filters["document_ids"] = document_ids
        elif document_id:
            filters["document_id"] = document_id

        query_embedding = embed_text(question)
        if ENABLE_HYBRID_RETRIEVAL:
            stages = hybrid_search_stages(
                vector_store,
                query=question,
                query_embedding=query_embedding,
                filters=filters,
                top_k=n_results,
                lexical_scan_limit=LEXICAL_SCAN_LIMIT,
            )
            stage_results = {
                f"production_dense:{search_label}": stages.dense,
                f"production_sparse:{search_label}": stages.lexical,
                f"production_hybrid:{search_label}": stages.fused,
            }
            results = stages.fused
        else:
            results = vector_store.search(
                query_embedding, filters=filters, top_k=n_results
            )
            stage_results = {f"production_dense:{search_label}": results}

        def serialize(result) -> Dict:
            meta = result.metadata or {}
            return {
                "text": result.text,
                "source": result.source or meta.get("source", "نامشخص"),
                "chunk": result.chunk or meta.get("chunk", "?"),
                "chunk_id": meta.get("chunk_id"),
                "document_id": result.document_id,
                "score": result.score,
                "chapter": meta.get("chapter"),
                "section": meta.get("section"),
                "subsection": meta.get("subsection"),
                "page": meta.get("page"),
                "parent_id": meta.get("parent_id"),
                "parent_title": meta.get("parent_title"),
                "parent_type": meta.get("parent_type"),
                "parent_role": meta.get("parent_role"),
                "parent_page_start": meta.get("parent_page_start"),
                "parent_page_end": meta.get("parent_page_end"),
            }

        if stage_recorder:
            for stage_name, stage_rows in stage_results.items():
                stage_recorder(stage_name, [serialize(row) for row in stage_rows])
        return [serialize(result) for result in results]
    except Exception as e:
        print(f"Error querying documents: {str(e)}", flush=True)
        raise RuntimeError("ارتباط با سرویس بازیابی اسناد برقرار نشد؛ کمی بعد دوباره تلاش کنید.") from e


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
    if RERANKER_PROVIDER == "openrouter":
        try:
            return openrouter_rerank(query, chunks, RERANKER_MODEL, top_k)
        except Exception as e:
            print(f"rerank: OpenRouter unavailable, falling back to dense order ({e})", flush=True)
            return chunks[:top_k]
    if RERANKER_PROVIDER != "local":
        print(f"rerank: unsupported RERANKER_PROVIDER={RERANKER_PROVIDER!r}, falling back to dense order", flush=True)
        return chunks[:top_k]
    model = _get_reranker()
    if model is None:
        return chunks[:top_k]
    start = time.perf_counter()
    pairs = [(query, c["text"]) for c in chunks]
    input_tokens = estimate_tokens_from_text(query) * len(chunks) + sum(
        estimate_tokens_from_text(c["text"]) for c in chunks
    )
    try:
        scores = model.predict(pairs)
        ranked = sorted(zip(chunks, scores), key=lambda cs: float(cs[1]), reverse=True)
        result = [c for c, _ in ranked[:top_k]]
        record_compute_usage_event(
            operation_type="reranking",
            provider="local_cpu" if RERANKER_DEVICE == "cpu" else "local_gpu",
            model=RERANKER_MODEL,
            device=RERANKER_DEVICE,
            latency_ms=round((time.perf_counter() - start) * 1000),
            input_count=len(pairs),
            input_chars=len(query or "") * len(chunks) + sum(len(c.get("text") or "") for c in chunks),
            chunk_count=len(chunks),
            pair_count=len(pairs),
            query_count=1,
            batch_size=len(pairs),
            status="success",
            metadata={
                "estimated_input_tokens": input_tokens,
                "top_k": top_k,
                "returned": len(result),
            },
        )
        return result
    except Exception as e:
        record_compute_usage_event(
            operation_type="reranking",
            provider="local_cpu" if RERANKER_DEVICE == "cpu" else "local_gpu",
            model=RERANKER_MODEL,
            device=RERANKER_DEVICE,
            latency_ms=round((time.perf_counter() - start) * 1000),
            input_count=len(pairs),
            input_chars=len(query or "") * len(chunks) + sum(len(c.get("text") or "") for c in chunks),
            chunk_count=len(chunks),
            pair_count=len(pairs),
            query_count=1,
            batch_size=len(pairs),
            status="error",
            error_type=e.__class__.__name__,
            metadata={
                "estimated_input_tokens": input_tokens,
                "top_k": top_k,
            },
        )
        print(f"rerank: falling back to dense order ({e})", flush=True)
        return chunks[:top_k]


def _selected_document_language(
    *, document_id: str = None, document_ids: List[str] = None, user_id: int = None,
) -> str | None:
    import db

    rows = []
    selected = [value for value in (document_ids or []) if value]
    if selected and user_id is not None:
        rows = db.list_assets_by_ids(user_id, selected)
    elif document_id:
        row = db.get_asset(document_id)
        if row and (user_id is None or row.get("user_id") == user_id):
            rows = [row]
    languages = set()
    for row in rows:
        profile = row.get("document_profile_json") or {}
        if isinstance(profile, str):
            try:
                profile = json.loads(profile)
            except json.JSONDecodeError:
                profile = {}
        language = profile.get("language") if isinstance(profile, dict) else None
        if language in {"fa", "en"}:
            languages.add(language)
    return next(iter(languages)) if len(languages) == 1 else "mixed"


def retrieve_with_metadata(
    query: str, document_id: str = None, document_ids: List[str] = None, user_id: int = None,
    top_k: int = None, retrieve_k: int = None, stage_recorder=None,
) -> tuple[List[Dict], Dict]:
    """Run one bounded production retrieval pass and return its safe telemetry."""
    top_k = top_k or RERANK_TOP_K
    candidate_k = retrieve_k or RETRIEVE_K

    search_number = 0

    def search(search_query: str) -> List[Dict]:
        nonlocal search_number
        search_number += 1
        return query_documents(
            search_query,
            n_results=candidate_k,
            document_id=document_id,
            document_ids=document_ids,
            user_id=user_id,
            stage_recorder=stage_recorder,
            search_label="original" if search_number == 1 else "rewrite",
        )

    def rerank_once(rerank_query: str, chunks: List[Dict]) -> List[Dict]:
        return rerank(rerank_query, chunks, min(len(chunks), max(top_k * 2, top_k)))

    if RETRIEVAL_MODE == "r2":
        rewrite_provider = get_chat_provider(
            "openrouter", PRIMARY_GENERATOR_MODEL, feature="chat_grounded",
        )
        result = retrieve_r2(
            query=query,
            document_language=_selected_document_language(
                document_id=document_id, document_ids=document_ids, user_id=user_id,
            ),
            search=search,
            rerank=rerank_once,
            finalize=lambda chunks: diversify_chunks(chunks, top_k),
            rewrite_provider=rewrite_provider,
            candidate_k=candidate_k,
            cross_language_rewrite_enabled=CROSS_LANGUAGE_REWRITE_ENABLED,
            stage_recorder=stage_recorder,
        )
        return result.chunks, result.telemetry

    wide = search(query)
    reranked = rerank_once(query, wide)
    return diversify_chunks(reranked, top_k), {
        "retrieval_mode": "r1",
        "rewrite_used": False,
        "rewrite_status": "disabled",
        "search_count": 1,
        "reranker_count": 1 if wide else 0,
    }


def retrieve(query: str, document_id: str = None, document_ids: List[str] = None, user_id: int = None,
             top_k: int = None, retrieve_k: int = None) -> List[Dict]:
    chunks, _metadata = retrieve_with_metadata(
        query,
        document_id=document_id,
        document_ids=document_ids,
        user_id=user_id,
        top_k=top_k,
        retrieve_k=retrieve_k,
    )
    return chunks


def diversify_chunks(chunks: List[Dict], top_k: int, max_per_parent: int = 2) -> List[Dict]:
    """Limit repetitive evidence only when multiple parent units are available.

    Flat articles commonly have one parent for the entire body. Applying a hard
    two-chunk cap there silently shrinks a five-item evidence budget to two and
    can remove the only detailed passage even after reranking found it.
    """
    parent_keys = []
    for chunk in chunks:
        identity = (
            chunk.get("parent_id")
            or chunk.get("parent_title")
            or _clean_heading(chunk.get("subsection"))
            or _clean_heading(chunk.get("section"))
            or _clean_heading(chunk.get("chapter"))
            or chunk.get("chunk")
        )
        parent_keys.append((chunk.get("document_id"), identity))
    effective_parent_limit = top_k if len(set(parent_keys)) <= 1 else max_per_parent

    diversified = []
    parent_counts = {}
    seen = set()
    for chunk, parent_key in zip(chunks, parent_keys):
        key = (chunk.get("document_id"), chunk.get("chunk"))
        if key in seen:
            continue
        if parent_counts.get(parent_key, 0) >= effective_parent_limit:
            continue
        seen.add(key)
        parent_counts[parent_key] = parent_counts.get(parent_key, 0) + 1
        diversified.append(chunk)
        if len(diversified) >= top_k:
            break
    return diversified


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
    junk = v.lower()
    if "www." in junk or "http://" in junk or "https://" in junk or "takbook" in junk or ".com" in junk:
        return None
    ordinal = (
        "اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
        "یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|"
        "هفدهم|هجدهم|نوزدهم|بیستم"
    )
    if re.match(r"^(فصل|بخش)\s+", v) and not re.match(
        rf"^(فصل|بخش)\s+([0-9۰-۹]+|{ordinal})(?:\s*[:.\-–—]\s*|\s+|$)",
        v,
    ):
        return None
    # Mis-detected paragraph-as-heading: too long, or ends like a sentence.
    if len(v) > 80 or len(v.split()) > 10 or v.rstrip().endswith((".", "؟", "!", "[1]")):
        return None
    return v


def _citation_label(chunk: Dict) -> str:
    """Builds a human-facing citation: filename - <heading> - PDF page N.

    For this corpus `chapter` is the junk "[]" placeholder and `section` is often a
    mis-detected paragraph, while `subsection` holds the real nearby heading. So we
    cite the most specific *trustworthy* heading available. Page is the original PDF
    page marker recorded during ingestion; chunk indexes are hidden from users."""
    parts = [chunk["source"]]
    heading = (
        _clean_heading(chunk.get("subsection"))
        or _clean_heading(chunk.get("section"))
        or _clean_heading(chunk.get("chapter"))
    )
    if heading:
        parts.append(heading)
    if chunk.get("page"):
        page_start = int(chunk["page"])
        page_end = int(chunk.get("page_end") or page_start)
        parts.append(f"صفحات {page_start} تا {page_end}" if page_end != page_start else f"صفحه {page_start}")
    return " - ".join(parts)


def _question_language(text: str) -> str:
    """Decide the answer language from the *question itself*, never from the
    retrieved context. Any Persian/Arabic-script character -> 'fa', otherwise 'en'.
    This is the fix that stops an English source document from dragging a Persian
    question's answer into English."""
    if re.search(r"[؀-ۿ]", text or ""):
        return "fa"
    return "en"


def _no_info_message(
    scope: str,
    language: str = "fa",
    question: str | None = None,
) -> str:
    topic = re.sub(r"\s+", " ", (question or "")).strip(" \t\r\n؟?!.،؛:")
    if len(topic) > 140:
        topic = topic[:137].rstrip() + "…"
    if language == "en":
        if topic and scope == "selected":
            return (
                f'The selected document does not provide enough information about '
                f'"{topic}" to answer reliably.'
            )
        return (
            "The selected document does not contain enough information to answer this question."
            if scope == "selected"
            else "The available documents do not contain enough information to answer this question."
        )
    if topic and scope == "selected":
        return f"سند انتخاب‌شده دربارهٔ «{topic}» اطلاعات کافی برای پاسخ قابل‌اعتماد ارائه نمی‌کند."
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
    task_instructions: str = None,
) -> List[Dict]:
    no_info_message = _no_info_message(
        scope, _question_language(question), question
    )
    return build_grounded_messages(
        question=question,
        chunks=relevant_chunks,
        citation_label=_citation_label,
        no_info_message=no_info_message,
        language=_question_language(question),
        selected_source=selected_source if scope == "selected" else None,
        task_instructions=task_instructions,
    )


def _build_free_chat_messages(question: str) -> List[Dict]:
    lang = _question_language(question)
    if lang == "fa":
        language_directive = "به فارسی روان، مستقیم و طبیعی پاسخ بده."
    else:
        language_directive = "Answer directly and naturally in English."
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful general-purpose assistant. "
                "This is free chat mode: no document context was selected, so you may use general knowledge. "
                + language_directive
            ),
        },
        {"role": "user", "content": question},
    ]


def _grounded_generation_orchestrator(
    primary_provider: ChatProvider = None,
    fallback_provider: ChatProvider = None,
    max_output_tokens: int = None,
) -> GroundedGenerationOrchestrator:
    return GroundedGenerationOrchestrator(
        primary_provider=primary_provider or get_chat_provider(
            "openrouter", PRIMARY_GENERATOR_MODEL, feature="chat_grounded",
        ),
        fallback_provider=fallback_provider or get_chat_provider(
            "openrouter", FALLBACK_GENERATOR_MODEL, feature="chat_grounded_fallback",
        ),
        primary_model=PRIMARY_GENERATOR_MODEL,
        fallback_model=FALLBACK_GENERATOR_MODEL,
        fallback_enabled=GENERATOR_FALLBACK_ENABLED,
        max_attempts=settings.rag_max_generator_attempts,
        max_output_tokens=max_output_tokens or settings.rag_max_output_tokens,
    )


def generate_free_response(question: str, chat_provider: ChatProvider = None) -> Dict:
    try:
        provider = chat_provider or CHAT_PROVIDER
        answer = provider.chat(
            messages=_build_free_chat_messages(question),
            options={"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
        ).strip()
        return {"answer": answer, "sources": []}
    except Exception as e:
        print(f"Error generating free chat response: {str(e)}")
        return {"answer": "خطا در تولید پاسخ.", "sources": []}


def _parse_conversation_explanation(raw: str) -> tuple[str, str]:
    """Accept common provider response shapes without leaking serialization.

    JSON mode is requested, but providers may still return fenced JSON, a short
    preamble, plain text, or a truncated final brace.  Conversation-only turns
    must handle those shapes locally and must never retry through retrieval.
    """
    value = (raw or "").strip()
    if not value:
        return "", "empty"
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE).strip()
    candidates = [unfenced]
    opening = unfenced.find("{")
    if opening > 0:
        candidates.append(unfenced[opening:])
    for candidate in candidates:
        try:
            payload, _end = json.JSONDecoder().raw_decode(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            explanation = str(payload.get("explanation") or payload.get("answer") or "").strip()
            if explanation:
                return explanation, "json"

    # Salvage the value of a cut-off JSON string while keeping escape handling
    # bounded.  This is deliberately narrower than repairing arbitrary JSON.
    match = re.search(
        r'["\'](?:explanation|answer)["\']\s*:\s*["\'](.+?)(?:["\']\s*[,}]|$)',
        unfenced,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        explanation = match.group(1).replace(r"\"", '"').replace(r"\n", " ").strip()
        if explanation:
            return explanation, "repaired_json"

    # Plain prose is already the desired user-facing format. Reject strings
    # that are only serialization debris.
    if not re.fullmatch(r"[\s{}\[\]\"':,]+", unfenced):
        return unfenced, "plain_text"
    return "", "malformed"


def generate_conversation_response(
    question: str,
    previous_answer: str,
    chat_provider: ChatProvider = None,
) -> Dict:
    """Explain the immediately preceding answer without document operations."""
    previous_answer = (previous_answer or "").strip()
    if not previous_answer:
        return {
            "answer": "لطفاً مشخص کنید کدام بخش از پاسخ قبلی را می‌خواهید توضیح بدهم.",
            "sources": [],
        }
    provider = chat_provider or CHAT_PROVIDER
    language = _question_language(question)
    language_rule = "به فارسی روان و کوتاه پاسخ بده." if language == "fa" else "Answer briefly in clear English."
    messages = [
        {
            "role": "system",
            "content": (
                "Explain only the immediately preceding assistant answer. "
                "Do not search documents, introduce new facts, or mention retrieval. "
                "Resolve a short clarification such as 'what does that mean?' against that answer. "
                "Return exactly one cohesive paragraph of 80 to 120 words. "
                "Do not enumerate sections, repeat citation markers, or end mid-sentence. "
                'Return JSON only: {"explanation": "..."}. '
                f"{language_rule}"
            ),
        },
        {
            "role": "user",
            "content": f"Previous assistant answer:\n{previous_answer[:12000]}\n\nFollow-up:\n{question}",
        },
    ]
    try:
        answer = provider.chat(
            messages=messages,
            options={
                "temperature": 0.0,
                "max_tokens": 360,
                "reasoning": {"effort": "none", "exclude": True},
                "seed": 17,
            },
            response_format="json",
        ).strip()
        answer, parse_mode = _parse_conversation_explanation(answer)
        if parse_mode == "repaired_json" and not re.search(r"[.!؟…»)]\s*$", answer):
            answer = ""
        if answer:
            usage = dict(getattr(provider, "last_call_metadata", {}) or {})
            return {
                "answer": answer,
                "sources": [],
                "generation_telemetry": {
                    "fallback_used": False,
                    "primary_input_tokens": int(usage.get("input_tokens") or 0),
                    "primary_output_tokens": int(usage.get("output_tokens") or 0),
                    "primary_cost": float(usage.get("cost_usd") or 0),
                    "fallback_cost": 0.0,
                    "total_generation_latency_ms": int(usage.get("latency_ms") or 0),
                    "response_parse_mode": parse_mode,
                },
            }
    except Exception as exc:  # Conversation fallback must never start retrieval.
        print(f"Error explaining previous answer: {exc.__class__.__name__}", flush=True)
    fallback = re.sub(r"\s*\[S\d+\]", "", previous_answer)
    sentences = re.split(r"(?<=[.!؟])\s+", fallback)
    concise = ""
    for sentence in sentences:
        if concise and len(concise) + len(sentence) > 900:
            break
        concise = f"{concise} {sentence}".strip()
    return {"answer": f"به زبان ساده: {concise}", "sources": []}


def generate_free_response_stream(question: str, chat_provider: ChatProvider = None) -> Iterable[Dict]:
    provider = chat_provider or CHAT_PROVIDER
    answer_parts = []
    try:
        for delta in provider.stream_chat(
            messages=_build_free_chat_messages(question),
            options={"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
        ):
            answer_parts.append(delta)
            yield {"type": "token", "delta": delta}
        answer = "".join(answer_parts).strip()
        yield {"type": "final", "answer": answer, "sources": []}
    except Exception as e:
        print(f"Error streaming free chat response: {str(e)}")
        if answer_parts:
            yield {"type": "final", "answer": "".join(answer_parts).strip(), "sources": []}
            return
        try:
            fallback = provider.chat(
                messages=_build_free_chat_messages(question),
                options={"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
            ).strip()
            if fallback:
                yield {"type": "token", "delta": fallback}
                yield {"type": "final", "answer": fallback, "sources": []}
                return
        except Exception as fallback_error:
            print(f"Error generating fallback free chat response: {fallback_error}")
        yield {"type": "error", "error": "خطا در تولید پاسخ."}


def generate_response(
    question: str,
    relevant_chunks: List[Dict],
    scope: str = "all",
    selected_source: str = None,
    chat_provider: ChatProvider = None,
    fallback_provider: ChatProvider = None,
    retrieval_metadata: Dict = None,
    task_instructions: str = None,
    extra_contract_error=None,
    max_output_tokens: int = None,
    support_scope_chunks: List[Dict] = None,
) -> Dict:
    no_info_message = _no_info_message(
        scope, _question_language(question), question
    )
    if not relevant_chunks:
        return {"answer": no_info_message, "sources": []}

    messages = _build_answer_messages(
        question,
        relevant_chunks,
        scope=scope,
        selected_source=selected_source,
        task_instructions=task_instructions,
    )
    payload = GenerationPayload.build(
        question=question,
        messages=messages,
        evidence=relevant_chunks,
        answer_language=_question_language(question),
        answerability_policy="evidence_only_no_answer_when_insufficient",
        citation_policy="validated_paragraph_end_source_markers",
        rewrite_used=bool((retrieval_metadata or {}).get("rewrite_used")),
    )
    orchestrator = _grounded_generation_orchestrator(
        chat_provider, fallback_provider, max_output_tokens=max_output_tokens,
    )
    locally_repaired: dict[str, str] = {}

    def validate_contract(raw: str) -> str | None:
        error = grounded_contract_error(raw, evidence_count=len(relevant_chunks))
        if error == "citation_marker_format_invalid":
            repaired = repair_grounded_contract(
                raw, evidence_count=len(relevant_chunks)
            )
            if repaired is not None:
                repaired_error = (
                    extra_contract_error(repaired)
                    if extra_contract_error is not None
                    else None
                )
                if repaired_error is None:
                    locally_repaired[raw] = repaired
                    return None
        if error is not None:
            return error
        return extra_contract_error(raw) if extra_contract_error is not None else None

    def parse_contract(raw: str) -> Dict:
        return parse_grounded_response(
            locally_repaired.get(raw, raw),
            chunks=relevant_chunks,
            citation_label=_citation_label,
            no_info_message=no_info_message,
            verify_support=True,
            support_scope_chunks=support_scope_chunks,
        )

    try:
        result, telemetry = orchestrator.generate(
            payload=payload,
            contract_error=validate_contract,
            parse_response=parse_contract,
        )
        telemetry["local_contract_repair_used"] = bool(locally_repaired)
        result["generation_telemetry"] = telemetry
        return result
    except GenerationUnavailableError as exc:
        print(f"Error generating grounded response: {exc.reason}", flush=True)
        return {
            "answer": "سرویس تولید پاسخ موقتاً در دسترس نیست؛ لطفاً دوباره تلاش کنید.",
            "sources": [],
            # Detailed failure reasons stay in server-side telemetry. The public
            # result exposes only a stable code and a controlled message.
            "error": {"code": "generation_unavailable"},
            "generation_telemetry": exc.telemetry,
        }


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
    fallback_provider: ChatProvider = None,
    retrieval_metadata: Dict = None,
) -> Iterable[Dict]:
    no_info_message = _no_info_message(
        scope, _question_language(question), question
    )
    if not relevant_chunks:
        yield {"type": "token", "delta": no_info_message}
        yield {"type": "final", "answer": no_info_message, "sources": []}
        return

    try:
        provider = chat_provider or CHAT_PROVIDER
        result = generate_response(
            question,
            relevant_chunks,
            scope=scope,
            selected_source=selected_source,
            chat_provider=provider,
            fallback_provider=fallback_provider,
            retrieval_metadata=retrieval_metadata,
        )
        if result.get("error"):
            yield {"type": "error", "error": result["answer"], "code": result["error"]["code"]}
            return
        yield {"type": "token", "delta": result["answer"]}
        yield {
            "type": "final",
            "answer": result["answer"],
            "sources": result["sources"],
            "generation_telemetry": result.get("generation_telemetry"),
        }
    except Exception as e:
        print(f"Error streaming response: {str(e)}")
        yield {"type": "error", "error": "خطا در تولید پاسخ."}


def answer_request(
    question: str,
    scope: str = "all",
    document_id: str = None,
    asset_ids: List[str] = None,
    user_id: int = None,
    selected_source: str = None,
    chat_provider_name: str = None,
    chat_model: str = None,
    generation_question: str = None,
    conversation_history: List[Dict] = None,
    conversation_id: str = None,
    request_id: str = None,
) -> Dict:
    """End-to-end answer pipeline used by the app:
        understand the message -> for each distinct question, retrieve its own context
    and answer it grounded -> assemble.

    A single question returns a single clean answer (same shape as generate_response).
    Several questions return one organized response that addresses each in turn, each
    grounded only in its own retrieved context (so questions never cross-contaminate
    and the context window never has to hold everything at once)."""
    # This is the sole production orchestrator. ENABLE_LANGGRAPH_RAG controls
    # whether eligible routes execute through the LangGraph state wrapper; it
    # never selects a different router or legacy retrieval pipeline.
    from backend.app.agents.rag_graph import answer_request as orchestrated_answer_request
    return orchestrated_answer_request(
        question,
        scope=scope,
        document_id=document_id,
        asset_ids=asset_ids,
        user_id=user_id,
        selected_source=selected_source,
        chat_provider_name=chat_provider_name,
        chat_model=chat_model,
        generation_question=generation_question,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
        request_id=request_id,
        langgraph_enabled=ENABLE_LANGGRAPH_RAG,
        semantic_supervisor_enabled=True,
    )


def answer_request_stream(
    question: str,
    scope: str = "all",
    document_id: str = None,
    asset_ids: List[str] = None,
    user_id: int = None,
    selected_source: str = None,
    chat_provider_name: str = None,
    chat_model: str = None,
    generation_question: str = None,
    conversation_history: List[Dict] = None,
    conversation_id: str = None,
    request_id: str = None,
) -> Iterable[Dict]:
    """Streaming twin of answer_request.

    Yields JSON-serializable events:
      trace: pipeline progress
      token: answer text delta
      final: final answer + sources
      error: recoverable failure
      done: stream is complete
    """
    from backend.app.agents.rag_graph import answer_request_stream as orchestrated_answer_request_stream
    yield from orchestrated_answer_request_stream(
        question,
        scope=scope,
        document_id=document_id,
        asset_ids=asset_ids,
        user_id=user_id,
        selected_source=selected_source,
        chat_provider_name=chat_provider_name,
        chat_model=chat_model,
        generation_question=generation_question,
        conversation_history=conversation_history,
        conversation_id=conversation_id,
        request_id=request_id,
        langgraph_enabled=ENABLE_LANGGRAPH_RAG,
        semantic_supervisor_enabled=True,
    )
    return
