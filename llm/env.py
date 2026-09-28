"""API keys from the process env, falling back to the repo .env (never logged)."""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def env_key(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    envp = REPO / ".env"
    if not envp.exists():
        return ""
    for line in envp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, val = line.split("=", 1)
        if k.strip() == name and val.strip().strip("\"'"):
            return val.strip().strip("\"'")
    return ""
