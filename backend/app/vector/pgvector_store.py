import json

from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import session_scope
from backend.app.vector.base import SearchResult, VectorChunk, VectorStore
from backend.app.vector.embeddings import embed_texts


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"


class PGVectorStore(VectorStore):
    """Current vector backend.

    The rest of the RAG pipeline must depend on VectorStore, not this class.
    A future QdrantStore should implement the same methods and keep PostgreSQL
    as the source of truth for users, files, conversations, and chunk metadata.
    """

    def add_chunks(self, chunks: list[VectorChunk]) -> int:
        if not chunks:
            return 0
        missing_embedding_indexes = [i for i, chunk in enumerate(chunks) if chunk.embedding is None]
        if missing_embedding_indexes:
            vectors = embed_texts([chunks[i].text for i in missing_embedding_indexes])
            chunks = list(chunks)
            for i, vector in zip(missing_embedding_indexes, vectors):
                source = chunks[i]
                chunks[i] = VectorChunk(
                    chunk_id=source.chunk_id,
                    user_id=source.user_id,
                    document_id=source.document_id,
                    source=source.source,
                    chunk_index=source.chunk_index,
                    text=source.text,
                    metadata=source.metadata,
                    embedding=vector,
                )

        with session_scope() as session:
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                metadata.setdefault("document_id", chunk.document_id)
                metadata.setdefault("source", chunk.source)
                metadata.setdefault("chunk", chunk.chunk_index)
                metadata.setdefault("user_id", chunk.user_id)
                session.execute(
                    text(
                        """
                        INSERT INTO document_chunks
                            (chunk_id, user_id, document_id, source, chunk_index, text,
                             metadata, embedding_model, embedding)
                        VALUES
                            (:chunk_id, :user_id, :document_id, :source, :chunk_index, :text,
                             CAST(:metadata AS jsonb), :embedding_model, CAST(:embedding AS vector))
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            document_id = EXCLUDED.document_id,
                            source = EXCLUDED.source,
                            chunk_index = EXCLUDED.chunk_index,
                            text = EXCLUDED.text,
                            metadata = EXCLUDED.metadata,
                            embedding_model = EXCLUDED.embedding_model,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "chunk_id": chunk.chunk_id,
                        "user_id": chunk.user_id,
                        "document_id": chunk.document_id,
                        "source": chunk.source,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                        "embedding_model": settings.embedding_model_path,
                        "embedding": _vector_literal(chunk.embedding or []),
                    },
                )
        return len(chunks)

    def search(self, query_embedding: list[float], filters: dict | None = None, top_k: int = 5) -> list[SearchResult]:
        filters = filters or {}
        clauses = []
        params = {
            "embedding": _vector_literal(query_embedding),
            "top_k": int(top_k),
        }
        if filters.get("user_id") is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = filters["user_id"]
        document_ids = [doc_id for doc_id in (filters.get("document_ids") or []) if doc_id]
        if document_ids:
            clauses.append("document_id = ANY(:document_ids)")
            params["document_ids"] = document_ids
        elif filters.get("document_id"):
            clauses.append("document_id = :document_id")
            params["document_id"] = filters["document_id"]
        if filters.get("source"):
            clauses.append("source = :source")
            params["source"] = filters["source"]

        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = text(
            f"""
            SELECT text, source, chunk_index, document_id, metadata,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS score
              FROM document_chunks
              {where_sql}
             ORDER BY embedding <=> CAST(:embedding AS vector)
             LIMIT :top_k
            """
        )
        with session_scope() as session:
            rows = session.execute(sql, params).mappings().all()
        results = []
        for row in rows:
            metadata = row["metadata"] or {}
            results.append(
                SearchResult(
                    text=row["text"],
                    source=row["source"],
                    chunk=row["chunk_index"],
                    document_id=row["document_id"],
                    score=float(row["score"]) if row["score"] is not None else None,
                    metadata=metadata,
                )
            )
        return results

    def delete_document(self, document_id: str, user_id: int | None = None) -> int:
        sql = "DELETE FROM document_chunks WHERE document_id = :document_id"
        params = {"document_id": document_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        with session_scope() as session:
            result = session.execute(text(sql), params)
            return result.rowcount or 0

    def delete_user_data(self, user_id: int) -> int:
        with session_scope() as session:
            result = session.execute(text("DELETE FROM document_chunks WHERE user_id = :user_id"), {"user_id": user_id})
            return result.rowcount or 0

    def count(self) -> int:
        with session_scope() as session:
            return int(session.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar_one())

