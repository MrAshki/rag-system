import json
import uuid
from time import sleep
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.app.core.config import settings
from backend.app.vector.base import SearchResult, VectorChunk, VectorStore
from backend.app.vector.embeddings import embed_texts


_POINT_NAMESPACE = uuid.UUID("6b83d4db-72d6-47cf-80ef-19e4d61f6b9f")


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


class QdrantStore(VectorStore):
    """Qdrant vector backend.

    PostgreSQL remains the source of truth for users, assets, conversations, and
    scan state. Qdrant owns only the vector index and chunk payload needed for
    retrieval.
    """

    def __init__(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client import models
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is not installed. Run `pip install -r requirements.txt` "
                "after adding Qdrant support."
            ) from exc

        self.models = models
        self.collection_name = settings.qdrant_collection
        self.client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
            check_compatibility=False,
        )
        self._ensure_collection()

    def _rest_url(self, path: str) -> str:
        return f"{settings.qdrant_url.rstrip('/')}{path}"

    def _rest_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        data = None
        headers = {"Content-Type": "application/json"}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        request = Request(
            self._rest_url(path),
            data=data,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _collection_exists_rest(self) -> bool:
        response = self._rest_request("GET", "/collections")
        collections = response.get("result", {}).get("collections", [])
        return any(item.get("name") == self.collection_name for item in collections)

    def _create_collection_rest(self) -> None:
        collection = quote(self.collection_name, safe="")
        self._rest_request(
            "PUT",
            f"/collections/{collection}",
            {
                "vectors": {
                    "size": settings.embedding_dim,
                    "distance": "Cosine",
                },
            },
        )

    def _count_rest(self, count_filter: dict[str, Any] | None = None) -> int:
        collection = quote(self.collection_name, safe="")
        body: dict[str, Any] = {"exact": True}
        if count_filter:
            body["filter"] = count_filter
        response = self._rest_request("POST", f"/collections/{collection}/points/count", body)
        return int(response.get("result", {}).get("count", 0))

    def _upsert_rest(self, points: list[dict[str, Any]]) -> None:
        collection = quote(self.collection_name, safe="")
        for start in range(0, len(points), 32):
            batch = points[start:start + 32]
            self._rest_request(
                "PUT",
                f"/collections/{collection}/points?wait=true",
                {"points": batch},
                timeout=90,
            )

    def _search_rest(self, query_embedding: list[float], query_filter, top_k: int):
        collection = quote(self.collection_name, safe="")
        body: dict[str, Any] = {
            "vector": query_embedding,
            "limit": int(top_k),
            "with_payload": True,
        }
        if query_filter is not None:
            body["filter"] = query_filter.model_dump(mode="json", exclude_none=True)
        response = self._rest_request("POST", f"/collections/{collection}/points/search", body, timeout=30)
        return response.get("result", [])

    def _scroll_rest(self, query_filter, limit: int) -> list[dict[str, Any]]:
        collection = quote(self.collection_name, safe="")
        remaining = max(0, int(limit))
        offset = None
        points: list[dict[str, Any]] = []
        while remaining > 0:
            body: dict[str, Any] = {
                "limit": min(remaining, 256),
                "with_payload": True,
                "with_vector": False,
            }
            if query_filter is not None:
                body["filter"] = query_filter.model_dump(mode="json", exclude_none=True)
            if offset is not None:
                body["offset"] = offset
            response = self._rest_request(
                "POST",
                f"/collections/{collection}/points/scroll",
                body,
                timeout=30,
            )
            result = response.get("result") or {}
            batch = result.get("points") or []
            points.extend(batch)
            remaining -= len(batch)
            offset = result.get("next_page_offset")
            if offset is None or not batch:
                break
        return points

    def _delete_rest(self, query_filter) -> None:
        if query_filter is None:
            return
        collection = quote(self.collection_name, safe="")
        self._rest_request(
            "POST",
            f"/collections/{collection}/points/delete?wait=true",
            {"filter": query_filter.model_dump(mode="json", exclude_none=True)},
            timeout=60,
        )

    def _ensure_collection(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                if self._collection_exists_rest():
                    return
            except Exception as exc:
                last_error = exc

            try:
                self._create_collection_rest()
                return
            except HTTPError as exc:
                last_error = exc
                if exc.code in {409, 422} and self._collection_exists_rest():
                    return
            except Exception as exc:
                last_error = exc

            try:
                if self.client.collection_exists(self.collection_name):
                    return
            except Exception as exc:
                last_error = exc

            try:
                self.client.get_collection(self.collection_name)
                return
            except Exception as exc:
                last_error = exc

            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=self.models.VectorParams(
                        size=settings.embedding_dim,
                        distance=self.models.Distance.COSINE,
                    ),
                )
                return
            except Exception as exc:
                last_error = exc
                sleep(min(attempt, 3))

        raise RuntimeError(
            f"Qdrant collection '{self.collection_name}' is not ready at {settings.qdrant_url}."
        ) from last_error

    def _filter(self, filters: dict[str, Any] | None = None):
        filters = filters or {}
        must = []
        if filters.get("user_id") is not None:
            must.append(
                self.models.FieldCondition(
                    key="user_id",
                    match=self.models.MatchValue(value=int(filters["user_id"])),
                )
            )

        document_ids = [doc_id for doc_id in (filters.get("document_ids") or []) if doc_id]
        if document_ids:
            must.append(
                self.models.FieldCondition(
                    key="document_id",
                    match=self.models.MatchAny(any=document_ids),
                )
            )
        elif filters.get("document_id"):
            must.append(
                self.models.FieldCondition(
                    key="document_id",
                    match=self.models.MatchValue(value=filters["document_id"]),
                )
            )

        if filters.get("source"):
            must.append(
                self.models.FieldCondition(
                    key="source",
                    match=self.models.MatchValue(value=filters["source"]),
                )
            )

        return self.models.Filter(must=must) if must else None

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

        point_payloads = []
        for chunk in chunks:
            metadata = dict(chunk.metadata or {})
            metadata.setdefault("document_id", chunk.document_id)
            metadata.setdefault("source", chunk.source)
            metadata.setdefault("chunk", chunk.chunk_index)
            metadata.setdefault("user_id", chunk.user_id)
            point_payloads.append(
                {
                    "id": _point_id(chunk.chunk_id),
                    "vector": chunk.embedding or [],
                    "payload": {
                        "chunk_id": chunk.chunk_id,
                        "user_id": int(chunk.user_id),
                        "document_id": chunk.document_id,
                        "source": chunk.source,
                        "chunk_index": int(chunk.chunk_index),
                        "text": chunk.text,
                        "metadata": metadata,
                        "embedding_model": settings.embedding_model,
                    },
                }
            )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                self._upsert_rest(point_payloads)
                return len(point_payloads)
            except Exception as exc:
                last_error = exc
                sleep(attempt)

        points = [self.models.PointStruct(**point) for point in point_payloads]
        try:
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        except Exception as exc:
            raise RuntimeError(
                f"Qdrant upsert failed for {len(point_payloads)} chunks in '{self.collection_name}'."
            ) from (last_error or exc)
        return len(point_payloads)

    def search(self, query_embedding: list[float], filters: dict | None = None, top_k: int = 5) -> list[SearchResult]:
        query_filter = self._filter(filters)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=int(top_k),
                with_payload=True,
            )
            points = response.points
        except AttributeError:
            try:
                points = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_embedding,
                    query_filter=query_filter,
                    limit=int(top_k),
                    with_payload=True,
                )
            except Exception:
                points = self._search_rest(query_embedding, query_filter, top_k)
        except Exception:
            points = self._search_rest(query_embedding, query_filter, top_k)

        results = []
        for point in points:
            if isinstance(point, dict):
                payload = point.get("payload") or {}
                score = point.get("score")
            else:
                payload = point.payload or {}
                score = point.score
            metadata = payload.get("metadata") or {}
            results.append(
                SearchResult(
                    text=payload.get("text") or "",
                    source=payload.get("source") or metadata.get("source") or "",
                    chunk=int(payload.get("chunk_index") or metadata.get("chunk") or 0),
                    document_id=payload.get("document_id") or metadata.get("document_id") or "",
                    score=float(score) if score is not None else None,
                    metadata=metadata,
                )
            )
        return results

    def list_chunks(self, filters: dict | None = None, limit: int = 2000) -> list[SearchResult]:
        query_filter = self._filter(filters)
        points = self._scroll_rest(query_filter, limit)
        results = []
        for point in points:
            payload = (point.get("payload") or {}) if isinstance(point, dict) else (point.payload or {})
            metadata = payload.get("metadata") or {}
            results.append(
                SearchResult(
                    text=payload.get("text") or "",
                    source=payload.get("source") or metadata.get("source") or "",
                    chunk=int(payload.get("chunk_index") or metadata.get("chunk") or 0),
                    document_id=payload.get("document_id") or metadata.get("document_id") or "",
                    metadata=metadata,
                )
            )
        return results

    def _count_filter(self, query_filter) -> int:
        if query_filter is None:
            return self.count()
        try:
            return int(self.client.count(
                collection_name=self.collection_name,
                count_filter=query_filter,
                exact=True,
            ).count)
        except Exception:
            try:
                filter_body = query_filter.model_dump(mode="json", exclude_none=True)
                return self._count_rest(filter_body)
            except Exception:
                return 0

    def delete_document(self, document_id: str, user_id: int | None = None) -> int:
        query_filter = self._filter({"document_id": document_id, "user_id": user_id})
        before = self._count_filter(query_filter)
        try:
            self._delete_rest(query_filter)
        except Exception:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=self.models.FilterSelector(filter=query_filter),
                wait=True,
            )
        return before

    def delete_user_data(self, user_id: int) -> int:
        query_filter = self._filter({"user_id": user_id})
        before = self._count_filter(query_filter)
        try:
            self._delete_rest(query_filter)
        except Exception:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=self.models.FilterSelector(filter=query_filter),
                wait=True,
            )
        return before

    def count(self) -> int:
        try:
            return int(self.client.count(collection_name=self.collection_name, exact=True).count)
        except Exception:
            return self._count_rest()
