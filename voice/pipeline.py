"""The voice call: Pipecat around the agent core, which runs unchanged.

    mic -> Sarvam STT -> turn detection (Silero VAD) -> agent core -> reply check
        -> normaliser -> speech (ElevenLabs or Sarvam) -> speaker
                                                       -> recording (WAV)

Barge-in is Pipecat's own: when the customer starts speaking over the bot, the
user turn handling interrupts the bot's speech. Each call writes the transcript to
runs/transcripts/<call_id>.json, as in text mode, and a stereo recording to
runs/recordings/<call_id>.wav (customer on the left, bot on the right).
"""

import asyncio
import wave

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
)
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
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

import config
from agent.core import Agent
from voice.guardrail import ReplyCheckStep
from voice.normaliser import speakable
from voice.tts import make_tts

# After the closing line, how long to wait for the bot to finish saying it.
CLOSING_WAIT_SECONDS = 20


class AgentStep(FrameProcessor):
    """The agent core as the pipeline's LLM step.

    Each finished user turn reaches this step as an LLMContextFrame. The step hands
    the turn's words to the agent and speaks the reply, one utterance per text
    frame. The agent works in its own task, one turn at a time: an interruption
    cancels a processor's pending work, and must not cut the agent off halfway
    through a turn (a tool call half done). Speculative turns are ignored.
    Once the agent has recorded the outcome and its closing line has been
    spoken, the step ends the call.
    """

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent
        self.end_call = None  # set by run_call: ends the pipeline
        self._turns: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker = None
        self._seen_messages = 0
        self._closing_started = False
        self._closing_spoken = asyncio.Event()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self._worker = self.create_task(self._work())
            await self._turns.put(None)  # None: open the call
            return
        if isinstance(frame, LLMContextFrame):
            if not frame.speculation and not self.agent.ended:
                for text in self._new_user_turns(frame.context):
                    await self._turns.put(text)
            return  # consumed: there is no other LLM after this step
        if isinstance(frame, BotStartedSpeakingFrame) and self.agent.ended:
            self._closing_started = True
        if isinstance(frame, BotStoppedSpeakingFrame) and self._closing_started:
            self._closing_spoken.set()
        if isinstance(frame, (EndFrame, CancelFrame)) and self._worker:
            await self.cancel_task(self._worker)
            self._worker = None
        await self.push_frame(frame, direction)

    def _new_user_turns(self, context: LLMContext) -> list[str]:
        """What the customer has said since the last turn handed to the agent."""
        messages = context.get_messages()
        new, self._seen_messages = messages[self._seen_messages :], len(messages)
        return [
            str(message["content"]).strip()
            for message in new
            if message.get("role") == "user" and str(message.get("content", "")).strip()
        ]

    async def _work(self):
        while True:
            text = await self._turns.get()
            if self.agent.ended:
                continue  # the customer spoke after the call was closed
            reply = await (
                self.agent.start() if text is None else self.agent.respond(text)
            )
            await self.push_frame(LLMFullResponseStartFrame())
            for utterance in reply.splitlines():
                await self.push_frame(LLMTextFrame(text=utterance + " "))
            await self.push_frame(LLMFullResponseEndFrame())
            if self.agent.ended:
                try:
                    await asyncio.wait_for(
                        self._closing_spoken.wait(), CLOSING_WAIT_SECONDS
                    )
                except TimeoutError:
                    logger.warning(
                        "Closing line not confirmed as spoken; ending the call anyway"
                    )
                if self.end_call:
                    await self.end_call()
                return


class NormaliserStep(FrameProcessor):
    """Rewrites each reply as words a speech service reads correctly."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame) and frame.text.strip():
            frame = LLMTextFrame(text=speakable(frame.text) + " ")
        await self.push_frame(frame, direction)


def save_recording(path, audio: bytes, sample_rate: int, num_channels: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(num_channels)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(audio)


def make_local_transport() -> BaseTransport:
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    return LocalAudioTransport(
        LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
    )


async def run_call(
    customer_id: str, version: str, transport: BaseTransport | None = None
) -> dict:
    """Run one voice call to the end and return its outcome. The transport defaults to
    the local mic and speaker; a test can pass another."""
    agent = Agent(customer_id, version, clock="wall")  # the call timer uses real time
    transport = transport or make_local_transport()

    stt = SarvamRealtimeSTTService(
        api_key=config.SARVAM_API_KEY,
        settings=SarvamRealtimeSTTService.Settings(
            model=config.SARVAM_STT_MODEL,
            language=None,  # detect per utterance: Hindi, English or a mix
            mode=config.SARVAM_STT_MODE,
        ),
    )
    # Turn detection: Sarvam's endpointing, timed by a local VAD. The same turn
    # handling interrupts the bot when the customer talks over it (barge-in).
    user_turns, _ = LLMContextAggregatorPair(
        LLMContext(),
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    agent_step = AgentStep(agent)
    recorder = AudioBufferProcessor(num_channels=2, auto_start_recording=True)
    recording_path = config.RUNS_DIR / "recordings" / f"{agent.state.call_id}.wav"

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_turns,
            agent_step,
            ReplyCheckStep(agent),
            NormaliserStep(),
            make_tts(),
            transport.output(),
            recorder,
        ]
    )

    @recorder.event_handler("on_audio_data")
    async def on_audio_data(_, audio: bytes, sample_rate: int, num_channels: int):
        save_recording(recording_path, audio, sample_rate, num_channels)

    latency = UserBotLatencyObserver()

    @latency.event_handler("on_latency_breakdown")
    async def on_latency_breakdown(_, breakdown: LatencyBreakdown):
        # Per turn: time from the end of the customer's speech to the bot's first audio.
        agent.events.append(
            {
                "type": "voice_latency",
                "total_seconds": round(breakdown.total_secs, 3),
                "parts": {
                    c.label: round(c.duration_secs, 3) for c in breakdown.contributions
                },
            }
        )
        for line in breakdown.turn_contribution_lines():
            logger.info(line)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[latency],
    )
    agent_step.end_call = worker.stop_when_done

    runner = WorkerRunner()
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        # However the call ended (closing line, hang-up, Ctrl+C), settle the outcome.
        agent.events.append({"type": "recording", "path": recording_path.as_posix()})
        outcome = await agent.finish()
    return outcome
