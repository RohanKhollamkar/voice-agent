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
# The eval judge: a non-Nemotron model, chosen in docs/results/final/judge_choice.md.
JUDGE_MODEL: str = _get_str("JUDGE_MODEL", "moonshotai/kimi-k3.1-pro")
# Reads the outcome off the transcript when the bot never recorded one (agent logic,
# not evaluation, so it did not change with the judge).
EXTRACTION_MODEL: str = _get_str(
    "EXTRACTION_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"
)

# Plays the customer in eval scenarios that use a persona instead of scripted turns
CUSTOMER_MODEL: str = _get_str("CUSTOMER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

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
# A fixed language, not auto-detect: with auto-detect, background noise came out as
# Bengali text. hi-IN with codemix still transcribes English and Hinglish.
SARVAM_STT_LANGUAGE: str = _get_str("SARVAM_STT_LANGUAGE", "hi-IN")
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
# Local voice detection, tightened against background noise (Pipecat's defaults:
# confidence 0.7, minimum volume 0.6, start 0.2 s).
VAD_CONFIDENCE: float = float(os.getenv("VAD_CONFIDENCE") or 0.8)
VAD_MIN_VOLUME: float = float(os.getenv("VAD_MIN_VOLUME") or 0.7)
VAD_START_SECS: float = float(os.getenv("VAD_START_SECS") or 0.3)
# Noise filter (voice/pipeline.py, NoiseFilter): a transcript with fewer real words than
# this, or in a script other than Latin or Devanagari, is dropped and logged as
# ignored_noise. Digits (a code, an amount) and the short answers below always pass,
# because "Yes.", "Friday" or "482913" is one word.
NOISE_MIN_WORDS: int = int(os.getenv("NOISE_MIN_WORDS") or 2)
NOISE_SHORT_ANSWERS: frozenset[str] = frozenset(
    [
        "yes",
        "yeah",
        "yep",
        "no",
        "nope",
        "haan",
        "han",
        "ha",
        "nahi",
        "nahin",
        "na",
        "ok",
        "okay",
        "ji",
        "sure",
        "right",
        "correct",
        "theek",
        "thik",
        "hello",
        "hi",
        "bye",
        "speaking",
        "हाँ",
        "हां",
        "हा",
        "नहीं",
        "ना",
        "जी",
        "ठीक",
        "हेलो",
        "हैलो",
        # One-word answers to "when?"
        "today",
        "tomorrow",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "aaj",
        "kal",
        "parso",
        "आज",
        "कल",
        "परसों",
    ]
)
# Barge-in: the customer interrupts the bot only after saying this many words
# (Pipecat's minimum-words strategy), so a cough or a word of echo does not cut it off.
BARGE_IN_MIN_WORDS: int = int(os.getenv("BARGE_IN_MIN_WORDS") or 2)
# Except a short answer made only of these words and/or digits ("Haan", "Yes", "482913"):
# it interrupts at once, because below the word minimum Pipecat would throw it away.
BARGE_IN_SHORT_ANSWERS: frozenset[str] = frozenset(
    ["yes", "yeah", "yep", "no", "nope", "haan", "han", "ha", "nahi", "nahin", "na",
     "ji", "हाँ", "हां", "हा", "नहीं", "ना", "जी"]
)  # fmt: skip
# After the customer interrupts the bot, wait this long for them to say more before
# the bot replies (their turn may arrive in pieces).
AFTER_INTERRUPTION_WAIT_SECONDS: float = float(
    os.getenv("AFTER_INTERRUPTION_WAIT_SECONDS") or 1.0
)
USER_SPEECH_TIMEOUT: float = float(
    os.getenv("USER_SPEECH_TIMEOUT") or 0.6
)  # manual mode
# Say a short holding line if the agent has not answered within this many seconds
# (0 turns it off).
VOICE_ACK_AFTER_SECONDS: float = float(os.getenv("VOICE_ACK_AFTER_SECONDS") or 1.5)
VOICE_ACK_LINE: str = "One moment."
# Sarvam speech (TTS_PROVIDER=sarvam, the default). bulbul:v4-flash has its own voice
# list (Sarvam's API returns it for an unknown speaker); ishita_en_customer is a female
# Indian English customer-service voice. Female alternatives: neha_en_customer,
# shalini_en_customer, simran_en_customer, sanchita_en_recovery.
SARVAM_TTS_MODEL: str = _get_str("SARVAM_TTS_MODEL", "bulbul:v4-flash")
SARVAM_TTS_VOICE: str = _get_str("SARVAM_TTS_VOICE", "ishita_en_customer")
# The bot's name in both versions (v2's prompt and the line added to v1's).
BOT_NAME: str = "Asha"
# v2's first line, spoken by code rather than generated, so it can never mention the card
# or the dues before the customer has confirmed who they are. v1 (the baseline) still
# generates its own opening.
OPENING_LINE: str = (
    "Hello, this is {bot_name}, an automated assistant from Mumbai Bank. "
    "Am I speaking with {customer_name}?"
)
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
# sarvam (default) | elevenlabs. Sarvam is the default because the ElevenLabs free
# quota ran out during testing; set elevenlabs to switch back.
TTS_PROVIDER: str = _get_str("TTS_PROVIDER", "sarvam").lower()
