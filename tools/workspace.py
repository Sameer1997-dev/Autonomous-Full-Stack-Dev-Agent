"""Shared agent workspace selection."""

import os
from pathlib import Path


_workspace = Path(os.environ.get("AGENT_WORKSPACE", "workspace")).expanduser().resolve()


def get_workspace() -> Path:
    return _workspace


def set_workspace(path) -> Path:
    global _workspace
    _workspace = Path(path).expanduser().resolve()
    return _workspace
