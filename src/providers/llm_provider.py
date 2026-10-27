"""
LLM provider layer.

* OpenAIProvider talks to any OpenAI-compatible chat endpoint (OpenAI itself,
  DeepSeek, OpenRouter, Together, Groq, HF router ...). Open-weight models are
  used through the same class by pointing `base_url` at the host.
* Every request is cached on disk (src/providers/cache.py). Re-running an
  experiment script with a warm cache reproduces the reported numbers without
  new API calls, which is how the results in results/ can be regenerated.
* Retries with exponential backoff on rate limits and transient errors.
* Token usage and dollar cost are tracked per call.
"""

from __future__ import annotations

import json
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from src.providers.cache import LLMCache

# USD per 1M tokens (input, output), list prices at the time of the runs
PRICES = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-ai/DeepSeek-V3-0324": (1.25, 1.25),
}


@dataclass
class LLMReply:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    cached: bool = False
    model: str = ""


def price(model: str, pt: int, ct: int) -> float:
    key = next((k for k in sorted(PRICES, key=len, reverse=True) if model.startswith(k)), None)
    if key is None:
        return 0.0
    pin, pout = PRICES[key]
    return (pt * pin + ct * pout) / 1_000_000


class LLMProvider(ABC):
    """Common interface. `generate` keeps the Phase 1 signature."""

    @abstractmethod
    def chat(self, messages: list[dict], temperature: float = 0.2, max_tokens: int = 4096,
             seed: Optional[int] = None, json_schema: Optional[dict] = None,
             sample: int = 0) -> LLMReply:
        ...

    @abstractmethod
    def model_name(self) -> str:
        ...

    def generate(self, prompt: str, system_prompt: Optional[str] = None,
                 temperature: float = 0.2, max_tokens: int = 4096) -> tuple[str, int, int]:
        msgs = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + \
            [{"role": "user", "content": prompt}]
        r = self.chat(msgs, temperature=temperature, max_tokens=max_tokens)
        return r.text, r.prompt_tokens, r.completion_tokens


class OpenAIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-4.1", api_key: Optional[str] = None,
                 base_url: Optional[str] = None, cache: Optional[LLMCache] = None,
                 supports_json_schema: bool = True, max_retries: int = 6,
                 offline: bool = False):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url
        self.cache = cache
        self.supports_json_schema = supports_json_schema
        self.max_retries = max_retries
        self.offline = offline            # cache-only replay, never call the API
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=120)
        return self._client

    def model_name(self) -> str:
        return self.model

    def chat(self, messages, temperature=0.2, max_tokens=4096, seed=None, json_schema=None,
             sample=0) -> LLMReply:
        request = {"model": self.model, "messages": messages, "temperature": temperature,
                   "max_tokens": max_tokens, "seed": seed, "sample": sample,
                   "schema": json_schema if self.supports_json_schema else None,
                   "base_url": self._base_url or "openai"}
        if self.cache is not None:
            hit = self.cache.get(request)
            if hit is not None:
                return LLMReply(text=hit["text"], prompt_tokens=hit["pt"], completion_tokens=hit["ct"],
                                cost_usd=price(self.model, hit["pt"], hit["ct"]),
                                seconds=hit.get("seconds", 0.0), cached=True, model=self.model)
        if self.offline:
            raise RuntimeError("offline replay mode: request not found in the LLM cache")

        kwargs = dict(model=self.model, messages=messages, temperature=temperature,
                      max_tokens=max_tokens)
        if seed is not None:
            kwargs["seed"] = seed
        if json_schema is not None:
            if self.supports_json_schema:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": json_schema}
            else:
                kwargs["response_format"] = {"type": "json_object"}
        start, delay = time.time(), 2.0
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._get_client().chat.completions.create(**kwargs)
                break
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                retryable = any(k in name for k in ("RateLimit", "Timeout", "Connection", "InternalServer",
                                                    "APIError", "ServiceUnavailable"))
                if not retryable or attempt == self.max_retries:
                    raise
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)
        text = resp.choices[0].message.content or ""
        pt = resp.usage.prompt_tokens if resp.usage else 0
        ct = resp.usage.completion_tokens if resp.usage else 0
        secs = time.time() - start
        if self.cache is not None:
            self.cache.put(request, {"text": text, "pt": pt, "ct": ct, "seconds": secs,
                                     "model_version": getattr(resp, "model", self.model),
                                     "fingerprint": getattr(resp, "system_fingerprint", None)})
        return LLMReply(text=text, prompt_tokens=pt, completion_tokens=ct,
                        cost_usd=price(self.model, pt, ct), seconds=secs, model=self.model)


class MockProvider(LLMProvider):
    """Deterministic provider for unit tests (no network)."""

    def __init__(self, model: str = "mock-model", responses: Optional[dict[str, str]] = None,
                 default_response: str = "// Mock implementation\n", script: Optional[list[str]] = None):
        self.model = model
        self._responses = responses or {}
        self._default = default_response
        self._script = list(script or [])
        self.call_count = 0
        self.last_prompt = ""
        self.prompts: list[str] = []

    def chat(self, messages, temperature=0.2, max_tokens=4096, seed=None, json_schema=None,
             sample=0) -> LLMReply:
        self.call_count += 1
        prompt = messages[-1]["content"]
        self.last_prompt = prompt
        self.prompts.append(prompt)
        if self._script:
            text = self._script.pop(0)
        else:
            text = next((r for k, r in self._responses.items() if k.lower() in prompt.lower()),
                        self._default)
        return LLMReply(text=text, prompt_tokens=len(prompt.split()), completion_tokens=len(text.split()),
                        model=self.model)

    def model_name(self) -> str:
        return self.model


# ---------------------------------------------------------------------------

MODEL_REGISTRY = {
    # name used in configs -> (provider kwargs)
    "gpt-4.1": dict(model="gpt-4.1-2025-04-14"),
    "gpt-4o-mini": dict(model="gpt-4o-mini-2024-07-18"),
    "gpt-4.1-mini": dict(model="gpt-4.1-mini-2025-04-14"),
}


def create_provider(name: str, cache: Optional[LLMCache] = None, offline: bool = False) -> LLMProvider:
    """Build a provider from a short model name.

    Open-weight models are configured through environment variables so no
    key ever lands in the repository:
        OPEN_MODEL_NAME, OPEN_MODEL_BASE_URL, OPEN_MODEL_API_KEY
    and are referred to as "open:<name>" in experiment configs.
    """
    if name == "mock":
        return MockProvider()
    if name.startswith("open:"):
        return OpenAIProvider(model=name[5:], api_key=os.environ.get("OPEN_MODEL_API_KEY", ""),
                              base_url=os.environ.get("OPEN_MODEL_BASE_URL"), cache=cache,
                              supports_json_schema=os.environ.get("OPEN_MODEL_JSON_SCHEMA", "0") == "1",
                              offline=offline)
    kw = MODEL_REGISTRY.get(name, dict(model=name))
    return OpenAIProvider(cache=cache, offline=offline, **kw)


# kept for backwards compatibility with the Phase 1 CLI
class AnthropicProvider(OpenAIProvider):
    """Phase 1 placeholder; Anthropic models are not used in Phase 2."""


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)
