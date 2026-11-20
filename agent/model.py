"""Shared Ollama model selection for planner, developer, and reviewer."""

import os


DEFAULT_MODEL = "qwen2.5-coder:7b"


def get_model():
    """Return the configured model, falling back to the project default."""
    return os.environ.get("AGENT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
