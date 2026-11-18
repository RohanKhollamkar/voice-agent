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

# Voice turn-taking (latency). Defaults are the settings the measurements chose; see
# docs/results/latency.md.
# vad: Sarvam's own end-of-speech detection ends the turn. manual: the local VAD is the
# only end-of-speech signal; Sarvam is told when speech ends.
STT_ENDPOINTING: str = _get_str("STT_ENDPOINTING", "vad")
SARVAM_STT_STREAM_TYPE: str = _get_str(
    "SARVAM_STT_STREAM_TYPE", "balanced"
)  # fast | balanced
# Sarvam waits this long in silence before ending the customer's turn. 700 ms was
# measured faster than Sarvam's default (about 0.35 s per turn) and still keeps a code
# read with pauses together (with the joining in voice/pipeline.py); 300-500 ms split it.
SARVAM_STT_SILENCE_MS: int | None = (
    int(os.getenv("SARVAM_STT_SILENCE_MS") or 700) or None
)
VAD_STOP_SECS: float = float(os.getenv("VAD_STOP_SECS") or 0.2)  # local VAD silence
USER_SPEECH_TIMEOUT: float = float(
    os.getenv("USER_SPEECH_TIMEOUT") or 0.6
)  # manual mode
# Say a short holding line if the agent has not answered within this many seconds
# (0 turns it off).
VOICE_ACK_AFTER_SECONDS: float = float(os.getenv("VOICE_ACK_AFTER_SECONDS") or 1.5)
VOICE_ACK_LINE: str = "One moment."
# The alternative speech service (TTS_PROVIDER=sarvam). An empty voice uses the model's default.
SARVAM_TTS_MODEL: str = _get_str("SARVAM_TTS_MODEL", "bulbul:v4-flash")
SARVAM_TTS_VOICE: str = _get_str("SARVAM_TTS_VOICE")
# Default is "Sarah", an ElevenLabs premade voice. Premade voices work on the free
# plan; voices from the ElevenLabs library need a paid plan to use over the API.
ELEVENLABS_VOICE_ID: str = _get_str("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# Language model calls
LLM_TIMEOUT_SECONDS: float = 8  # after this the bot falls back to BACKUP_MODEL
EXTRACTION_TIMEOUT_SECONDS: float = 60  # post-call outcome extraction, not live
# Waits before retrying a rate-limited judge, extraction or simulated-customer request
RATE_LIMIT_WAITS_SECONDS: tuple[int, ...] = (10, 30, 60)

# Bank rules (from the brief; the bot's figures come from here, never from the model)
MONTHLY_INTEREST_RATE_PERCENT: float = 3.5
LATE_FEE_RUPEES: int = 750
LATE_FEE_BALANCE_THRESHOLD: int = 10_000  # late fee applies only above this balance

# The brief's limit on call length. Text-mode evals estimate it from word count.
CALL_MAX_SECONDS: int = 180
CALL_CLOSE_WARNING_SECONDS: int = 150  # v2: the bot is told to move to close
SPEAKING_WORDS_PER_MINUTE: int = 150
CALL_LENGTH_TOLERANCE_SECONDS: int = 30  # allowed on top, for the word-count estimate

# Two wrong OTPs end the call with a callback (our decision, see CLAUDE.md)
MAX_OTP_ATTEMPTS: int = 2

# Where calls are recorded
RUNS_DIR: Path = Path("runs")
TIMEZONE: str = "Asia/Kolkata"

# Behaviour
ENFORCE_OTP: bool = _get_bool("ENFORCE_OTP", True)
BOT_VERSION: str = _get_str("BOT_VERSION", "v2")
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "elevenlabs").lower()
