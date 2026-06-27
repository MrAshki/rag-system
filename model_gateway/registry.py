import os

from model_gateway.base import ChatProvider
from model_gateway.providers.deepseek_provider import DeepSeekChatProvider
from model_gateway.providers.gemini_provider import GeminiChatProvider
from model_gateway.providers.ollama_provider import OllamaChatProvider


_chat_providers = {}


def _default_model_for_provider(provider: str) -> str:
    if provider == "ollama":
        model = os.getenv("CHAT_MODEL") or os.getenv("OLLAMA_MODEL")
        if not model:
            raise RuntimeError(
                "OLLAMA_MODEL or CHAT_MODEL is not set. Add it to .env before running."
            )
        return model
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    if provider == "deepseek":
        return os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
    raise RuntimeError(f"Unsupported CHAT_PROVIDER={provider!r}.")


def get_chat_provider(provider: str = None, model: str = None) -> ChatProvider:
    provider = (provider or os.getenv("CHAT_PROVIDER", "ollama")).strip().lower()
    model = (model or _default_model_for_provider(provider)).strip()
    if not model:
        model = _default_model_for_provider(provider)
    key = (provider, model)
    if key in _chat_providers:
        return _chat_providers[key]

    if provider == "ollama":
        _chat_providers[key] = OllamaChatProvider(model=model)
        return _chat_providers[key]

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to .env before using Gemini."
            )
        _chat_providers[key] = GeminiChatProvider(model=model, api_key=api_key)
        return _chat_providers[key]

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY is not set. Add it to .env before using DeepSeek."
            )
        _chat_providers[key] = DeepSeekChatProvider(model=model, api_key=api_key)
        return _chat_providers[key]

    raise RuntimeError(f"Unsupported CHAT_PROVIDER={provider!r}.")


def list_chat_model_options():
    default_provider = os.getenv("CHAT_PROVIDER", "ollama").strip().lower()
    ollama_model = os.getenv("OLLAMA_MODEL") or os.getenv("CHAT_MODEL")
    gemini_model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    deepseek_model = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
    options = []

    if ollama_model:
        options.append({
            "provider": "ollama",
            "model": ollama_model,
            "label": f"محلی - {ollama_model}",
            "enabled": True,
            "default": default_provider == "ollama",
        })

    options.append({
        "provider": "gemini",
        "model": gemini_model,
        "label": f"Gemini - {gemini_model}",
        "enabled": bool(os.getenv("GEMINI_API_KEY")),
        "default": default_provider == "gemini",
    })
    options.append({
        "provider": "deepseek",
        "model": deepseek_model,
        "label": f"DeepSeek - {deepseek_model}",
        "enabled": bool(os.getenv("DEEPSEEK_API_KEY")),
        "default": default_provider == "deepseek",
    })
    return options
