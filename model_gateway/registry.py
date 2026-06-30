import os
import re

from model_gateway.base import ChatProvider
from model_gateway.providers.deepseek_provider import DeepSeekChatProvider
from model_gateway.providers.gemini_provider import GeminiChatProvider
from model_gateway.providers.litellm_provider import LiteLLMChatProvider
from model_gateway.providers.ollama_provider import OllamaChatProvider


_chat_providers = {}


def _default_provider() -> str:
    return (os.getenv("DEFAULT_CHAT_PROVIDER") or os.getenv("CHAT_PROVIDER") or "litellm").strip().lower()


def _env_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _litellm_model_for_feature(feature: str = None) -> str:
    if feature:
        key = _env_key(feature)
        feature_model = (
            os.getenv(f"LITELLM_{key}_MODEL")
            or os.getenv(f"LITELLM_MODEL_{key}")
        )
        if feature_model:
            return feature_model.strip()
    return (
        os.getenv("DEFAULT_CHAT_MODEL")
        or os.getenv("LITELLM_MODEL")
        or "chat_free"
    ).strip()


def _default_model_for_provider(provider: str, feature: str = None) -> str:
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
    if provider == "litellm":
        return _litellm_model_for_feature(feature)
    raise RuntimeError(f"Unsupported CHAT_PROVIDER={provider!r}.")


def get_chat_provider(provider: str = None, model: str = None, feature: str = None) -> ChatProvider:
    provider = (provider or _default_provider()).strip().lower()
    model = (model or _default_model_for_provider(provider, feature=feature)).strip()
    if not model:
        model = _default_model_for_provider(provider, feature=feature)
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

    if provider == "litellm":
        api_key = (
            os.getenv("LITELLM_MASTER_KEY")
            or os.getenv("LITELLM_API_KEY")
            or os.getenv("LITELLM_LOCAL_TEST_KEY")
            or "sk-local-litellm-test-key"
        )
        _chat_providers[key] = LiteLLMChatProvider(
            model=model,
            api_key=api_key,
            base_url=os.getenv("LITELLM_BASE_URL") or "http://localhost:4000",
        )
        return _chat_providers[key]

    raise RuntimeError(f"Unsupported CHAT_PROVIDER={provider!r}.")


def list_chat_model_options():
    default_provider = _default_provider()
    ollama_model = os.getenv("OLLAMA_MODEL") or os.getenv("CHAT_MODEL")
    gemini_model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    deepseek_model = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"
    litellm_models = [
        item.strip()
        for item in (os.getenv("LITELLM_CHAT_MODEL_OPTIONS") or _litellm_model_for_feature("chat_free")).split(",")
        if item.strip()
    ]
    litellm_models = list(dict.fromkeys(litellm_models))
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
    for index, litellm_model in enumerate(litellm_models):
        options.append({
            "provider": "litellm",
            "model": litellm_model,
            "label": "LiteLLM - Chat" if litellm_model == "chat_free" else f"LiteLLM - {litellm_model}",
            "enabled": os.getenv("LITELLM_ENABLED", "true").strip().lower() == "true",
            "default": default_provider == "litellm" and index == 0,
        })
    return options
