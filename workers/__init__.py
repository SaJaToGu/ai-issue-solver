"""
workers — Worker-Adapter-Paket für den AI Issue Solver.

Jeder Provider (Codex, OpenCode, Mistral Vibe, OpenRouter Direct, Aider-Derivate)
wird durch einen fokussierten Adapter repräsentiert, der das WorkerAdapter-Protokoll
aus workers.base implementiert.

Verfügbare Adapter:
    - CodexAdapter         (workers.codex_adapter)
    - OpenCodeAdapter      (workers.opencode_adapter)
    - MistralVibeAdapter   (workers.mistral_vibe_adapter)
    - OpenRouterDirectAdapter (workers.openrouter_direct_adapter)
    - AiderAdapter         (workers.aider_adapter)

Der OpenRouter-Worker für direkte API-Aufrufe liegt in workers.openrouter_worker.
"""
