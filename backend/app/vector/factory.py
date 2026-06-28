from backend.app.core.config import settings
from backend.app.vector.base import VectorStore
from backend.app.vector.pgvector_store import PGVectorStore

_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        if settings.vector_backend != "pgvector":
            raise RuntimeError(
                f"Unsupported VECTOR_BACKEND={settings.vector_backend!r}. "
                "Only 'pgvector' is implemented; 'qdrant' is reserved for a future adapter."
            )
        _store = PGVectorStore()
    return _store
