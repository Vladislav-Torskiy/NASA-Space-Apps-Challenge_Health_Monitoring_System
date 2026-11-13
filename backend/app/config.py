"""Configuration & rules loader for ASTRA-Med backend."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _load_dotenv_if_present() -> None:
    """Load simple KEY=VALUE pairs from .env if present without external deps."""
    for candidate in (REPO_ROOT / ".env", BACKEND_DIR / ".env"):
        if not candidate.is_file():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv_if_present()


class Settings:
    """Application settings resolved dynamically from environment variables."""

    @property
    def data_dir(self) -> Path:
        env_val = os.getenv("DATA_DIR")
        if env_val:
            return Path(env_val)
        return REPO_ROOT / "data"

    @property
    def sqlite_db_path(self) -> Path:
        env_val = os.getenv("SQLITE_DB_PATH", "./astra_med.db")
        p = Path(env_val)
        if not p.is_absolute():
            return BACKEND_DIR / p
        return p

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    @property
    def gemini_model(self) -> str:
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    @property
    def vision_timeout_seconds(self) -> float:
        return float(os.getenv("VISION_TIMEOUT_SECONDS", "7"))

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


settings = Settings()


@lru_cache(maxsize=4)
def load_nasa_rules(data_dir_str: str | None = None) -> dict[str, Any]:
    """Load NASA HRP & CSA rules JSON from data directory."""
    base = Path(data_dir_str) if data_dir_str else settings.data_dir
    rules_path = base / "nasa_hrp_rules.json"
    with rules_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_seed_data() -> dict[str, Any]:
    """Load the 24-day baseline seed JSON."""
    seed_path = settings.data_dir / "seed_30days.json"
    with seed_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
