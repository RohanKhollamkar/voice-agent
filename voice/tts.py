"""The speech service, chosen by TTS_PROVIDER, so switching needs no other change.

TTS_PROVIDER=sarvam (default): Sarvam Bulbul (SARVAM_TTS_MODEL), in Indian English.
TTS_PROVIDER=elevenlabs: ElevenLabs Flash v2.5, voice ELEVENLABS_VOICE_ID.
"""

from pipecat.services.tts_service import TTSService

import config


def make_tts() -> TTSService:
    """The configured speech service, ready to put in a pipeline."""
    if config.TTS_PROVIDER == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=config.ELEVENLABS_API_KEY,
            settings=ElevenLabsTTSService.Settings(
                voice=config.ELEVENLABS_VOICE_ID, model=config.ELEVENLABS_MODEL
            ),
        )
    if config.TTS_PROVIDER == "sarvam":
        from pipecat.services.sarvam.tts import SarvamTTSService
        from pipecat.transcriptions.language import Language

        settings = SarvamTTSService.Settings(
            model=config.SARVAM_TTS_MODEL, language=Language.EN_IN
        )
        if config.SARVAM_TTS_VOICE:  # otherwise the model's default speaker
            settings.voice = config.SARVAM_TTS_VOICE
        return SarvamTTSService(api_key=config.SARVAM_API_KEY, settings=settings)
    raise ValueError(
        f"TTS_PROVIDER must be elevenlabs or sarvam, not '{config.TTS_PROVIDER}'"
    )
