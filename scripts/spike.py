"""Stage 1 voice spike: mic -> Sarvam STT -> OpenRouter LLM -> ElevenLabs TTS -> speaker.

Proves the stack works end to end and prints where each turn's time went.
No collections logic here.

Run from the repo root (use headphones, there is no echo cancellation):
    python -m scripts.spike
    python -m scripts.spike --model "$BACKUP_MODEL"
"""

import argparse
import asyncio

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TranscriptionFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    UserBotLatencyObserver,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openrouter.llm import OpenRouterLLMService
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.transports.local.audio import (
    LocalAudioTransport,
    LocalAudioTransportParams,
)

import config

SYSTEM_PROMPT = "You are a polite assistant. Reply in one short English sentence."


class TranscriptPrinter(BaseObserver):
    """Prints each final transcript, so we can see which script Hindi words arrive in."""

    def __init__(self):
        super().__init__(observe_every_push=False)

    async def on_push_frame(self, data: FramePushed):
        if isinstance(data.frame, TranscriptionFrame):
            print(
                f"\nYOU ({data.frame.language or 'language unknown'}): {data.frame.text}"
            )


def print_turn(breakdown: LatencyBreakdown, turn: int) -> None:
    """Print one turn's latency: each stage's own number, then the whole timeline."""
    print(f"--- turn {turn} latency ---")
    # Time to first byte as each service reports it: for STT, end of speech to
    # final transcript; for the LLM, request to first token; for TTS, text to first audio.
    for metric in breakdown.ttfb:
        print(f"{metric.duration_secs:6.3f}s  time to first byte  [{metric.processor}]")
    # Every part of the wait, in order, summing to the total from the end of
    # your speech to the first bot audio.
    for line in breakdown.turn_contribution_lines():
        print(line)


async def main(model: str) -> None:
    transport = LocalAudioTransport(
        LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
    )

    stt = SarvamRealtimeSTTService(
        api_key=config.SARVAM_API_KEY,
        settings=SarvamRealtimeSTTService.Settings(
            model=config.SARVAM_STT_MODEL,
            language=None,  # detect per utterance: Hindi, English or a mix
            mode=config.SARVAM_STT_MODE,
        ),
    )

    llm = OpenRouterLLMService(
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        settings=OpenRouterLLMService.Settings(
            model=model,
            # `reasoning` is OpenRouter's own field, so it travels in extra_body.
            extra={"extra_body": {"reasoning": config.LLM_REASONING}},
        ),
    )

    tts = ElevenLabsTTSService(
        api_key=config.ELEVENLABS_API_KEY,
        settings=ElevenLabsTTSService.Settings(
            voice=config.ELEVENLABS_VOICE_ID,
            model=config.ELEVENLABS_MODEL,
        ),
    )

    context = LLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
    # Sarvam decides when the turn ends; the local VAD times the end of speech.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    latency = UserBotLatencyObserver()
    turns = 0

    @latency.event_handler("on_latency_breakdown")
    async def on_latency_breakdown(observer, breakdown: LatencyBreakdown):
        nonlocal turns
        turns += 1
        print_turn(breakdown, turns)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[latency, TranscriptPrinter()],
    )

    print(f"Model: {model}. Speak after the pipeline starts; Ctrl+C to stop.")
    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice spike with per-turn latency.")
    parser.add_argument("--model", default=config.BOT_MODEL, help="OpenRouter model ID")
    asyncio.run(main(parser.parse_args().model))
