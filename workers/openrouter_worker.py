"""
Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe.

Verwendet die OpenRouter API (https://openrouter.ai) ohne Aider-Abhängigkeit.
Unterstützt Model-Overrides wie `mistralai/mistral-large`.
"""

import os
import requests
from typing import Optional, Dict, Any


class OpenRouterWorker:
    """Direkter OpenRouter Worker für OpenAI-kompatible API-Aufrufe."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "mistralai/mistral-large",
        base_url: str = "https://openrouter.ai/api/v1",
        referer: Optional[str] = None,
        x_title: Optional[str] = None,
    ):
        """
        Args:
            api_key: OpenRouter API Key. Wird standardmäßig aus `OPENROUTER_API_KEY` gelesen.
            model: OpenRouter Model-String (z. B. `mistralai/mistral-large`).
            base_url: OpenRouter API Base URL.
            referer: HTTP-Referer für OpenRouter.
            x_title: X-Title für OpenRouter.
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY ist nicht gesetzt.")

        self.model = model
        self.base_url = base_url
        self.referer = referer or os.getenv("OPENROUTER_REFERER", "https://github.com/anomalyco/opencode")
        self.x_title = x_title or os.getenv("OPENROUTER_X_TITLE", "OpenCode")

    def build_headers(self) -> Dict[str, str]:
        """Erzeugt die HTTP-Header für OpenRouter API-Aufrufe."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.referer,
            "X-Title": self.x_title,
        }

    def generate(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Führt einen OpenRouter API-Aufruf durch und gibt die Antwort zurück.

        Args:
            prompt: Eingabe-Prompt für das Model.
            temperature: Sampling-Temperatur.
            max_tokens: Maximale Token-Anzahl für die Antwort.

        Returns:
            Generierte Antwort als String.

        Raises:
            ValueError: Bei API-Fehlern oder ungültigen Antworten.
        """
        headers = self.build_headers()
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

        result = response.json()
        if "choices" not in result or not result["choices"]:
            raise ValueError("Ungültige Antwort von OpenRouter API.")

        return result["choices"][0]["message"]["content"]