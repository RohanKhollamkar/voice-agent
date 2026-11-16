"""Settings loaded from the environment (.env). Import from here; never hard-code these in logic."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_str(name: str, default: str = "") -> str:
    """Like os.getenv, but an empty value in .env falls back to the default."""
    return os.getenv(name, "").strip() or default


# Secrets and endpoints (no defaults)
SARVAM_API_KEY: str = _get_str("SARVAM_API_KEY")
ELEVENLABS_API_KEY: str = _get_str("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID: str = _get_str("ELEVENLABS_VOICE_ID")
OPENROUTER_API_KEY: str = _get_str("OPENROUTER_API_KEY")
WEBHOOK_URL: str = _get_str("WEBHOOK_URL")

# Models (OpenRouter IDs)
BOT_MODEL: str = _get_str("BOT_MODEL", "google/gemma-4-31b-it:free")
BACKUP_MODEL: str = _get_str("BACKUP_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
JUDGE_MODEL: str = _get_str("JUDGE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

# Provider settings
OPENROUTER_BASE_URL: str = _get_str(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)
# OpenRouter's unified switch for thinking; sent with every chat request.
LLM_REASONING: dict = {"enabled": False}
SARVAM_STT_MODEL: str = _get_str("SARVAM_STT_MODEL", "saaras:v3-realtime")
# transcribe | codemix | translit | verbatim | translate
SARVAM_STT_MODE: str = _get_str("SARVAM_STT_MODE", "codemix")
ELEVENLABS_MODEL: str = _get_str("ELEVENLABS_MODEL", "eleven_flash_v2_5")

# Language model calls
LLM_TIMEOUT_SECONDS: float = 8  # after this the bot falls back to BACKUP_MODEL
EXTRACTION_TIMEOUT_SECONDS: float = 30  # post-call outcome extraction, not live

# Bank rules (from the brief; the bot's figures come from here, never from the model)
MONTHLY_INTEREST_RATE_PERCENT: float = 3.5
LATE_FEE_RUPEES: int = 750
LATE_FEE_BALANCE_THRESHOLD: int = 10_000  # late fee applies only above this balance

# Where calls are recorded
RUNS_DIR: Path = Path("runs")
TIMEZONE: str = "Asia/Kolkata"

# Behaviour
ENFORCE_OTP: bool = _get_bool("ENFORCE_OTP", True)
BOT_VERSION: str = _get_str("BOT_VERSION", "v2")
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "elevenlabs").lower()
