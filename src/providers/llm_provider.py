"""
LLM provider abstraction layer.

Defines a common interface for different LLM providers (OpenAI, Anthropic, Mock)
to enable cross-model evaluation as required by project Part 3.
"""

import os
import time
from abc import ABC, abstractmethod
from typing import Optional

from src.schemas import GeneratedCode, Language


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All providers must implement the generate method, which takes a prompt
    and returns the model's text response.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[str, int, int]:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system-level instructions.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.

        Returns:
            Tuple of (response_text, prompt_tokens, completion_tokens).
        """
        pass

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        pass


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (GPT-4, GPT-4o, etc.).

    Also works with any OpenAI-compatible endpoint (e.g., Azure OpenAI,
    local vLLM servers) by setting the base_url parameter.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[str, int, int]:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("Install openai: pip install openai")

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        text = response.choices[0].message.content or ""
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0

        return text, prompt_tokens, completion_tokens

    def model_name(self) -> str:
        return self.model


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude models."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
    ):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[str, int, int]:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

        client = anthropic.Anthropic(api_key=self._api_key)

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = client.messages.create(**kwargs)

        text = response.content[0].text if response.content else ""
        prompt_tokens = response.usage.input_tokens if response.usage else 0
        completion_tokens = response.usage.output_tokens if response.usage else 0

        return text, prompt_tokens, completion_tokens

    def model_name(self) -> str:
        return self.model


class MockProvider(LLMProvider):
    """Mock LLM provider for testing without API calls.

    Returns predefined responses or echoes the prompt.
    Used for unit testing and baseline validation.
    """

    def __init__(
        self,
        model: str = "mock-model",
        responses: Optional[dict[str, str]] = None,
        default_response: str = "// Mock implementation\n",
    ):
        self.model = model
        self._responses = responses or {}
        self._default = default_response
        self.call_count = 0
        self.last_prompt = ""

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> tuple[str, int, int]:
        self.call_count += 1
        self.last_prompt = prompt

        # Check for keyword-matched responses
        for keyword, response in self._responses.items():
            if keyword.lower() in prompt.lower():
                return response, len(prompt.split()), len(response.split())

        return self._default, len(prompt.split()), len(self._default.split())

    def model_name(self) -> str:
        return self.model
