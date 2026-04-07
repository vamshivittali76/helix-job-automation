"""
Unified LLM access: local Ollama (free, default) or OpenAI cloud (optional).

Helix does not require paid APIs. Install Ollama from https://ollama.ai and run:
  ollama pull llama3.2
Then start the Ollama app (or `ollama serve`). Configure secrets.yaml — see secrets.template.yaml.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import requests
import yaml

ROOT = Path(__file__).parent.parent.parent
SECRETS_PATH = ROOT / "config" / "secrets.yaml"


def load_secrets() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _openai_key_valid(key: str) -> bool:
    k = (key or "").strip()
    return bool(k and "your-" not in k.lower() and not k.startswith("sk-your"))


def ollama_reachable(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _resolve_provider(secrets: dict) -> str:
    p = (secrets.get("llm_provider") or "auto").strip().lower()
    if p not in ("ollama", "openai", "auto"):
        return "auto"
    return p


def _pick_backend(secrets: dict) -> Optional[str]:
    """Return 'ollama' | 'openai' or None if nothing usable."""
    provider = _resolve_provider(secrets)
    base = (secrets.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")

    if provider == "ollama":
        return "ollama" if ollama_reachable(base) else None

    if provider == "openai":
        return "openai" if _openai_key_valid(secrets.get("openai_api_key", "")) else None

    # auto: prefer free local
    if ollama_reachable(base):
        return "ollama"
    if _openai_key_valid(secrets.get("openai_api_key", "")):
        return "openai"
    return None


class _CompletionsNamespace:
    def __init__(self, parent: "UnifiedLLMClient"):
        self._parent = parent

    def create(
        self,
        model: str | None = None,
        messages: list | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        return self._parent._complete(
            model=model,
            messages=messages or [],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_kwargs=kwargs,
        )


class _ChatNamespace:
    def __init__(self, parent: "UnifiedLLMClient"):
        self.completions = _CompletionsNamespace(parent)


class UnifiedLLMClient:
    """
    Duck-compatible with ``openai.OpenAI().chat.completions.create`` return shape
    (``response.choices[0].message.content``).
    """

    def __init__(self, secrets: dict, backend: str):
        self._secrets = secrets
        self._backend = backend
        self._ollama_base = (secrets.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
        self._ollama_model = (secrets.get("ollama_model") or "llama3.2").strip()
        self._openai = None
        if backend == "openai":
            from openai import OpenAI

            self._openai = OpenAI(api_key=secrets.get("openai_api_key", ""))

    @property
    def chat(self) -> _ChatNamespace:
        return _ChatNamespace(self)

    def _complete(
        self,
        *,
        model: str | None,
        messages: list,
        temperature: float,
        max_tokens: int | None,
        response_format: dict | None,
        extra_kwargs: dict,
    ) -> SimpleNamespace:
        if self._backend == "openai" and self._openai is not None:
            kw = {
                "model": model or "gpt-4o-mini",
                "messages": messages,
                "temperature": temperature,
            }
            if max_tokens is not None:
                kw["max_tokens"] = max_tokens
            if response_format is not None:
                kw["response_format"] = response_format
            kw.update({k: v for k, v in extra_kwargs.items() if k in ("top_p", "frequency_penalty", "presence_penalty")})
            return self._openai.chat.completions.create(**kw)

        # Ollama
        url = f"{self._ollama_base}/api/chat"
        payload: dict = {
            "model": self._ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"

        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        content = (data.get("message") or {}).get("content") or ""
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content.strip()))]
        )


def create_llm_client(secrets: dict | None = None) -> Optional[UnifiedLLMClient]:
    """
    Return a client if any backend is available, else None.

    - ``llm_provider: ollama`` — only local Ollama
    - ``llm_provider: openai`` — only OpenAI API key
    - ``llm_provider: auto`` — Ollama first, then OpenAI
    """
    if secrets is None:
        secrets = load_secrets()
    backend = _pick_backend(secrets)
    if not backend:
        return None
    return UnifiedLLMClient(secrets, backend)


def llm_backend_label(secrets: dict | None = None) -> str:
    """Human-readable label for logs / errors."""
    if secrets is None:
        secrets = load_secrets()
    b = _pick_backend(secrets)
    if b == "ollama":
        m = (secrets.get("ollama_model") or "llama3.2").strip()
        return f"Ollama ({m})"
    if b == "openai":
        return "OpenAI"
    return "none"
