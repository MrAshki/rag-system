import os
import threading

import torch
from sentence_transformers import SentenceTransformer

from backend.app.core.config import settings

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_model = None
_model_lock = threading.Lock()


def embedding_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(settings.embedding_model_path, device=embedding_device())
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = get_embedding_model()
    with _model_lock:
        vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.astype("float32").tolist()


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]

