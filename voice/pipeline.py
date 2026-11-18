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
import re
import time
import wave

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TTSSpeakFrame,
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
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

import config
from agent import mock_bank
from agent.core import Agent
from voice.guardrail import ReplyCheckStep
from voice.normaliser import speakable
from voice.tts import make_tts

# After the closing line, how long to wait for the bot to finish saying it.
CLOSING_WAIT_SECONDS = 20
# How long to wait for the rest of a code read out in parts ("482" ... "913").
CODE_JOIN_SECONDS = 4.0


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
        self._held: list[
            str | None
        ] = []  # a turn taken out of the queue but not yet used

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

    async def _next_turn(self) -> str | None:
        return self._held.pop(0) if self._held else await self._turns.get()

    def _is_code_part(self, text: str | None) -> bool:
        """Only digits, fewer than the OTP has, while the bot is waiting for the OTP."""
        state = self.agent.state
        if text is None or not state.otp_sent or state.otp_verified:
            return False
        digits, rest = re.sub(r"\D", "", text), re.sub(r"[\d\s.,-]", "", text)
        otp_length = len(mock_bank.get_customer(state.customer_id)["otp"])
        return bool(digits) and not rest and len(digits) < otp_length

    async def _join_code_parts(self, text: str | None) -> str | None:
        """A customer reading out the OTP may pause between digits, and the pause can
        end the turn early ("482", then "913"). The first part would count as a wrong
        code, and two wrong codes end the call. So while the bot is waiting for the OTP,
        a turn that is only part of a code waits up to CODE_JOIN_SECONDS for the rest."""
        while self._is_code_part(text):
            try:
                more = await asyncio.wait_for(self._next_turn(), CODE_JOIN_SECONDS)
            except TimeoutError:
                break
            if more is None or re.sub(r"[\d\s.,-]", "", more):  # not more digits
                self._held.insert(0, more)
                break
            self.agent._log(type="voice_code_joined", parts=[text, more])
            text = f"{text} {more}"
        return text

    async def _answer(self, text: str | None) -> str:
        """The agent's reply. If it takes longer than VOICE_ACK_AFTER_SECONDS, say a
        holding line first. "One moment." commits to nothing, so it cannot contradict
        whatever follows (an "Okay." could, before a refusal)."""
        started = time.monotonic()
        work = asyncio.ensure_future(
            self.agent.start() if text is None else self.agent.respond(text)
        )
        wait = config.VOICE_ACK_AFTER_SECONDS
        if wait and text is not None:
            done, _ = await asyncio.wait({work}, timeout=wait)
            if not done:
                # A speak frame goes straight to speech; text frames would wait in the
                # speech service's sentence buffer until the reply arrived.
                await self.push_frame(TTSSpeakFrame(text=config.VOICE_ACK_LINE))
                self.agent._log(type="voice_ack", text=config.VOICE_ACK_LINE)
        reply = await work
        self.agent._log(
            type="voice_agent_time", seconds=round(time.monotonic() - started, 3)
        )
        return reply

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
            text = await self._join_code_parts(await self._next_turn())
            if self.agent.ended:
                continue  # the customer spoke after the call was closed
            # The response starts now, while the agent works: the latency observer
            # times the agent from this frame to its first text.
            await self.push_frame(LLMFullResponseStartFrame())
            reply = await self._answer(text)
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


class MicGate(FrameProcessor):
    """Half-duplex echo handling for laptop speakers with no headphones: while the bot
    is speaking, and for a short tail after, the mic's audio is replaced with silence,
    so the bot never hears (and answers, or is interrupted by) its own voice. Silence
    rather than nothing, so speech-to-text and the recording keep a steady stream. The
    cost: the customer cannot interrupt the bot (no barge-in)."""

    TAIL_SECONDS = 0.4  # the room's echo lingers a little after the bot stops

    def __init__(self):
        super().__init__()
        self._bot_speaking = False
        self._open_at = 0.0  # the mic is live again from this time

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._open_at = time.monotonic() + self.TAIL_SECONDS
        elif isinstance(frame, InputAudioRawFrame) and (
            self._bot_speaking or time.monotonic() < self._open_at
        ):
            frame = InputAudioRawFrame(
                audio=b"\0" * len(frame.audio),
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
        await self.push_frame(frame, direction)


def make_local_transport() -> BaseTransport:
    from pipecat.transports.local.audio import (
        LocalAudioTransport,
        LocalAudioTransportParams,
    )

    return LocalAudioTransport(
        LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
    )


async def run_call(
    customer_id: str,
    version: str,
    transport: BaseTransport | None = None,
    echo: str = "none",
    handle_sigint: bool = True,
) -> dict:
    """Run one voice call to the end and return its outcome. The transport defaults to
    the local mic and speaker; a test or the browser connection can pass another.
    echo="half-duplex" mutes the mic while the bot speaks (see MicGate)."""
    agent = Agent(customer_id, version, clock="wall")  # the call timer uses real time
    transport = transport or make_local_transport()

    stt_settings = SarvamRealtimeSTTService.Settings(
        model=config.SARVAM_STT_MODEL,
        language=None,  # detect per utterance: Hindi, English or a mix
        mode=config.SARVAM_STT_MODE,
        stream_type=config.SARVAM_STT_STREAM_TYPE,
    )
    if config.SARVAM_STT_SILENCE_MS:
        stt_settings.silence_duration_ms = config.SARVAM_STT_SILENCE_MS
    stt = SarvamRealtimeSTTService(
        api_key=config.SARVAM_API_KEY,
        endpointing=config.STT_ENDPOINTING,
        settings=stt_settings,
    )
    # Turn detection. With "vad" endpointing Sarvam decides when the customer has
    # finished, and the local VAD only times it. With "manual" the local VAD is the one
    # end-of-speech signal: Sarvam is told when speech ends, and the turn ends once the
    # transcript is in and USER_SPEECH_TIMEOUT has passed. Either way the same turn
    # handling interrupts the bot when the customer talks over it (barge-in).
    vad = SileroVADAnalyzer(params=VADParams(stop_secs=config.VAD_STOP_SECS))
    user_params = LLMUserAggregatorParams(vad_analyzer=vad)
    if config.STT_ENDPOINTING == "manual":
        user_params.user_turn_strategies = UserTurnStrategies(
            stop=[
                SpeechTimeoutUserTurnStopStrategy(
                    user_speech_timeout=config.USER_SPEECH_TIMEOUT
                )
            ]
        )
    user_turns, _ = LLMContextAggregatorPair(LLMContext(), user_params=user_params)
    agent_step = AgentStep(agent)
    recorder = AudioBufferProcessor(num_channels=2, auto_start_recording=True)
    recording_path = config.RUNS_DIR / "recordings" / f"{agent.state.call_id}.wav"

    pipeline = Pipeline(
        [
            transport.input(),
            *([MicGate()] if echo == "half-duplex" else []),
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
        # Per turn: time from the end of the customer's speech to the bot's first audio,
        # by stage. The agent's own time (model calls and tools) is the part the
        # observer cannot name, between the response starting and the first text.
        parts: dict[str, float] = {}
        for part in breakdown.contributions:
            parts[part.label] = round(parts.get(part.label, 0) + part.duration_secs, 3)
        agent._log(
            type="voice_latency",
            measured_from=str(breakdown.measured_from),
            total_seconds=round(breakdown.total_secs, 3),
            parts=parts,
        )
        for line in breakdown.turn_contribution_lines():
            logger.info(line)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[latency],
    )
    agent_step.end_call = worker.stop_when_done

    runner = WorkerRunner(handle_sigint=handle_sigint)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        # However the call ended (closing line, hang-up, Ctrl+C), settle the outcome.
        agent._log(type="recording", path=recording_path.as_posix())
        outcome = await agent.finish()
    return outcome
