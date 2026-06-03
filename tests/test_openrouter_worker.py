"""
Tests für den direkten OpenRouter Worker.
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from workers.openrouter_worker import OpenRouterWorker


class TestOpenRouterWorker(unittest.TestCase):
    """Tests für OpenRouterWorker."""

    def setUp(self):
        self.api_key = "test_api_key"
        self.model = "mistralai/mistral-large"
        self.prompt = "Test prompt"
        self.worker = OpenRouterWorker(
            api_key=self.api_key,
            model=self.model,
        )

    def test_init_missing_api_key(self):
        """Testet, dass ein Fehler geworfen wird, wenn kein API-Key vorhanden ist."""
        with self.assertRaises(ValueError):
            OpenRouterWorker(api_key=None)

    def test_build_headers(self):
        """Testet die Header-Konstruktion."""
        headers = self.worker.build_headers()
        self.assertEqual(headers["Authorization"], "Bearer test_api_key")
        self.assertEqual(headers["HTTP-Referer"], "https://github.com/anomalyco/opencode")
        self.assertEqual(headers["X-Title"], "OpenCode")

    @patch("requests.post")
    def test_generate_success(self, mock_post):
        """Testet einen erfolgreichen API-Aufruf."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        response = self.worker.generate(self.prompt)
        self.assertEqual(response, "Test response")
        mock_post.assert_called_once_with(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self.worker.build_headers(),
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": self.prompt}],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        )

    @patch("requests.post")
    def test_generate_api_error(self, mock_post):
        """Testet API-Fehlerbehandlung."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with self.assertRaises(Exception):
            self.worker.generate(self.prompt)

    @patch("requests.post")
    def test_generate_invalid_response(self, mock_post):
        """Testet ungültige API-Antworten."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"invalid": "response"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with self.assertRaises(ValueError):
            self.worker.generate(self.prompt)


if __name__ == "__main__":
    unittest.main()