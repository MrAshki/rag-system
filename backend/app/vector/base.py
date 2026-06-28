from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorChunk:
    chunk_id: str
    user_id: int
    document_id: str
    source: str
    chunk_index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass(frozen=True)
class SearchResult:
    text: str
    source: str
    chunk: int
    document_id: str
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    @abstractmethod
    def add_chunks(self, chunks: list[VectorChunk]) -> int:
        raise NotImplementedError

    @abstractmethod
    def search(self, query_embedding: list[float], filters: dict | None = None, top_k: int = 5) -> list[SearchResult]:
        raise NotImplementedError

    @abstractmethod
    def delete_document(self, document_id: str, user_id: int | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def delete_user_data(self, user_id: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

