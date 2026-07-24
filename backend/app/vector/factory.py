from backend.app.core.config import settings
from backend.app.vector.base import VectorStore
from backend.app.vector.pgvector_store import PGVectorStore

_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        if settings.vector_backend == "pgvector":
            _store = PGVectorStore()
        elif settings.vector_backend == "qdrant":
            from backend.app.vector.qdrant_store import QdrantStore

            _store = QdrantStore()
        else:
            raise RuntimeError(
                f"Unsupported VECTOR_BACKEND={settings.vector_backend!r}. "
                "Use 'pgvector' or 'qdrant'."
            )
    return _store
