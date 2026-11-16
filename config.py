"""Settings loaded from the environment (.env). Import from here; never hard-code these in logic."""

import os

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

# Behaviour
ENFORCE_OTP: bool = _get_bool("ENFORCE_OTP", True)
BOT_VERSION: str = _get_str("BOT_VERSION", "v2")
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "elevenlabs").lower()
