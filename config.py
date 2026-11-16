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
NVIDIA_API_KEY: str = _get_str("NVIDIA_API_KEY")
WEBHOOK_URL: str = _get_str("WEBHOOK_URL")

# Models (NVIDIA API IDs)
BOT_MODEL: str = _get_str("BOT_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
BACKUP_MODEL: str = _get_str("BACKUP_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
JUDGE_MODEL: str = _get_str("JUDGE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

# Plays the customer in eval scenarios that use a persona instead of scripted turns
CUSTOMER_MODEL: str = _get_str("CUSTOMER_MODEL", JUDGE_MODEL)

# Provider settings
NVIDIA_BASE_URL: str = _get_str(
    "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
)
# Sent with every bot request to turn the model's thinking off. NVIDIA has no
# single switch; this one is read by the Nemotron chat template.
LLM_EXTRA_BODY: dict = {"chat_template_kwargs": {"enable_thinking": False}}
SARVAM_STT_MODEL: str = _get_str("SARVAM_STT_MODEL", "saaras:v3-realtime")
# transcribe | codemix | translit | verbatim | translate
SARVAM_STT_MODE: str = _get_str("SARVAM_STT_MODE", "codemix")
ELEVENLABS_MODEL: str = _get_str("ELEVENLABS_MODEL", "eleven_flash_v2_5")
# Default is "Sarah", an ElevenLabs premade voice. Premade voices work on the free
# plan; voices from the ElevenLabs library need a paid plan to use over the API.
ELEVENLABS_VOICE_ID: str = _get_str("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# Language model calls
LLM_TIMEOUT_SECONDS: float = 8  # after this the bot falls back to BACKUP_MODEL
EXTRACTION_TIMEOUT_SECONDS: float = 60  # post-call outcome extraction, not live

# Bank rules (from the brief; the bot's figures come from here, never from the model)
MONTHLY_INTEREST_RATE_PERCENT: float = 3.5
LATE_FEE_RUPEES: int = 750
LATE_FEE_BALANCE_THRESHOLD: int = 10_000  # late fee applies only above this balance

# The brief's limit on call length. Text-mode evals estimate it from word count.
CALL_MAX_SECONDS: int = 180
SPEAKING_WORDS_PER_MINUTE: int = 150

# Where calls are recorded
RUNS_DIR: Path = Path("runs")
TIMEZONE: str = "Asia/Kolkata"

# Behaviour
ENFORCE_OTP: bool = _get_bool("ENFORCE_OTP", True)
BOT_VERSION: str = _get_str("BOT_VERSION", "v2")
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "elevenlabs").lower()
