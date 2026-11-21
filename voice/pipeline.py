"""The voice call: Pipecat around the agent core, which runs unchanged.

    mic -> Sarvam STT -> turn detection (Silero VAD) -> agent core -> reply check
        -> normaliser -> speech (ElevenLabs or Sarvam) -> speaker
                                                       -> recording (WAV)

Barge-in is Pipecat's own: when the customer speaks over the bot, the user turn
handling interrupts the bot's speech, once they have said BARGE_IN_MIN_WORDS words
(or at once for a short answer: digits and/or yes/no, such as the OTP or "Haan").
Transcripts that look like noise are dropped before turn detection (NoiseFilter). Each call writes the transcript to
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
    ClientConnectedFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
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
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.sarvam.stt import SarvamRealtimeSTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop.external_user_turn_stop_strategy import (
    ExternalUserTurnStopStrategy,
)
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
        # Set by run_call for the browser connection: the opening line waits for the
        # browser to connect, so it is not spoken into a connection nobody hears yet.
        self.client_connected: asyncio.Event | None = None
        self._bot_speaking = False
        self._interrupted = False  # the customer talked over the bot
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
        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            if self.agent.ended:
                self._closing_started = True
        if isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            if self._closing_started:
                self._closing_spoken.set()
        if isinstance(frame, InterruptionFrame) and self._bot_speaking:
            self._interrupted = True
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

    async def _join_after_interruption(self, text: str | None) -> str | None:
        """After the customer talks over the bot, their turn often arrives in pieces
        ("no no", then "I already paid"). Wait AFTER_INTERRUPTION_WAIT_SECONDS of
        silence for more before answering, so the bot replies to all of it."""
        while text is not None:
            try:
                more = await asyncio.wait_for(
                    self._next_turn(), config.AFTER_INTERRUPTION_WAIT_SECONDS
                )
            except TimeoutError:
                break
            if more is None:
                self._held.insert(0, more)
                break
            self.agent._log(type="voice_turn_joined", parts=[text, more])
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
            text = await self._next_turn()
            if text is None and self.client_connected is not None:
                await self.client_connected.wait()  # open once the browser is there
            if self._interrupted and text is not None:
                self._interrupted = False
                text = await self._join_after_interruption(text)
            text = await self._join_code_parts(text)
            if self.agent.ended:
                continue  # the customer spoke after the call was closed
            # The response starts now, while the agent works: the latency observer
            # times the agent from this frame to its first text.
            await self.push_frame(LLMFullResponseStartFrame())
            reply = await self._answer(text)
            # The turn's lines (from before and after a tool call) go to speech as one
            # text, so they play in order in one audio context and never cut each
            # other off. Speech still starts at the first sentence.
            await self.push_frame(LLMTextFrame(text=" ".join(reply.splitlines()) + " "))
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
                # The bot ends the call: the demo console disconnects the browser on this.
                self.agent._log(type="call_ended", by="bot", name=config.BOT_NAME)
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


class TurnLatencyObserver(UserBotLatencyObserver):
    """Pipecat's per-stage latency breakdown, kept anchored to the customer's stop.

    Pipecat clears that anchor on every interruption. Our turns start from the
    transcript (minimum-words barge-in), after the customer has stopped, and starting
    a turn sends an interruption: the anchor was lost and the breakdown fell back to
    the call connecting. That one interruption is skipped here. A real barge-in still
    resets the breakdown: the customer starting to speak clears the stop moment first.
    (Relies on Pipecat's private _user_stopped_time, as of pipecat-ai 1.16.)
    """

    async def on_push_frame(self, data: FramePushed):
        if (
            isinstance(data.frame, InterruptionFrame)
            and self._user_stopped_time is not None
        ):
            return  # the turn starting after the customer stopped: keep the anchor
        await super().on_push_frame(data)


class FirstAudioObserver(BaseObserver):
    """Time to the bot's first audio, per bot turn, logged as voice_first_audio.

    The opening line is measured from the moment the call connected (the browser
    connecting, or the pipeline starting when there is no browser). Every reply is
    measured from the moment the customer stopped speaking (the local voice detector's
    stop, minus its silence wait) to the bot's first audio, which may be the "One
    moment." holding line. If that stop moment is missing for a reply, nothing is
    measured and voice_first_audio_missing is logged instead of a wrong number.

    Pipecat's UserBotLatencyObserver loses that moment here: it clears it on the
    interruption sent when a customer turn starts, and our turns start from the
    transcript (minimum-words barge-in), after the customer has stopped. Its
    breakdown then counts from the connection instead.
    """

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent
        self._seen: set[int] = set()  # a frame is pushed past every processor
        self._connected_at: float | None = None
        self._stopped_at: float | None = None
        self._turns_started = 0  # LLM responses begun: the opening, then replies
        self._turns_measured = 0

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame
        if frame.id in self._seen or not isinstance(
            frame,
            (
                StartFrame,
                ClientConnectedFrame,
                VADUserStartedSpeakingFrame,
                VADUserStoppedSpeakingFrame,
                LLMFullResponseStartFrame,
                BotStartedSpeakingFrame,
            ),
        ):
            return
        self._seen.add(frame.id)
        now = time.monotonic()
        if isinstance(frame, StartFrame) and self._connected_at is None:
            self._connected_at = now
        elif isinstance(frame, ClientConnectedFrame):
            self._connected_at = now  # the browser is there: the opening's start
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            self._stopped_at = None
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._stopped_at = now - frame.stop_secs
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._turns_started += 1
        elif self._turns_measured < self._turns_started:  # BotStartedSpeakingFrame
            self._turns_measured = self._turns_started
            if self._turns_started == 1:
                start, measured_from = self._connected_at, "call_connected"
            else:
                start, measured_from = self._stopped_at, "customer_stopped"
            if start is None:
                self.agent._log(
                    type="voice_first_audio_missing", turn=self._turns_started
                )
                logger.warning("No customer-stopped moment for this turn: no latency")
            else:
                self.agent._log(
                    type="voice_first_audio",
                    seconds=round(now - start, 3),
                    measured_from=measured_from,
                )
            self._stopped_at = None


def save_recording(path, audio: bytes, sample_rate: int, num_channels: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(num_channels)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(audio)


# Letters from any script, and the ones a customer's words can be in: Latin (English,
# romanised Hindi) and Devanagari (Hindi).
ANY_LETTER = re.compile(r"[^\W\d_]")
OUR_LETTER = re.compile(r"[A-Za-z\u00c0-\u024f\u0900-\u097f]")


def noise_reason(text: str) -> str | None:
    """Why a transcript looks like noise rather than speech, or None if it is speech."""
    if any(not OUR_LETTER.match(c) for c in ANY_LETTER.findall(text)):
        return "other_script"  # e.g. Bengali text from background noise
    if re.search(r"\d", text):
        return None  # a code or an amount, however short
    words = [w for w in text.split() if OUR_LETTER.search(w)]
    if len(words) >= config.NOISE_MIN_WORDS:
        return None
    if (
        len(words) == 1
        and words[0].strip(".,!?।").lower() in config.NOISE_SHORT_ANSWERS
    ):
        return None  # "Yes.", "Haan."
    return "too_short"


def is_short_answer(text: str) -> bool:
    """Only digits and/or yes/no words: "482913", "Haan", "Yes, 4 8 2". Only, not
    contains, so the bot's own words leaking into the mic ("your minimum due is
    ₹2,425") never count."""
    words = re.sub(r"[.,!?।\-]", " ", text).lower().split()
    return bool(words) and all(
        w.isdigit() or w in config.BARGE_IN_SHORT_ANSWERS for w in words
    )


class ShortAnswerMinWordsStrategy(MinWordsUserTurnStartStrategy):
    """Pipecat's minimum-words strategy (a turn interrupts the bot only after
    BARGE_IN_MIN_WORDS words), except that a short answer interrupts at once. Without
    this, a code or a "Haan" said while the bot is still talking is one word, below the
    minimum, and Pipecat drops it: the customer's OTP was lost that way."""

    async def process_frame(self, frame: Frame):
        transcript = isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame))
        if transcript and self._bot_speaking and is_short_answer(frame.text):
            logger.debug(f"Short answer interrupts the bot: {frame.text!r}")
            await self.report_user_turn_started()
            return
        await super().process_frame(frame)


class NoiseFilter(FrameProcessor):
    """Between speech-to-text and turn detection: drops transcripts that look like
    noise (see noise_reason), so they neither start a turn, interrupt the bot nor
    reach the agent. Final ones are logged in the transcript as ignored_noise."""

    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            reason = noise_reason(frame.text)
            if reason:
                if isinstance(frame, TranscriptionFrame):
                    self.agent._log(
                        type="ignored_noise", text=frame.text, reason=reason
                    )
                return
        await self.push_frame(frame, direction)


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
    agent: Agent | None = None,
) -> dict:
    """Run one voice call to the end and return its outcome. The transport defaults to
    the local mic and speaker; a test or the browser connection can pass another.
    echo="half-duplex" mutes the mic while the bot speaks (see MicGate). A caller that
    needs the agent before the call starts (the demo console) can pass its own."""
    # The call timer uses real time.
    agent = agent or Agent(customer_id, version, clock="wall")
    transport = transport or make_local_transport()

    stt_settings = SarvamRealtimeSTTService.Settings(
        model=config.SARVAM_STT_MODEL,
        # Fixed, not detected: detection turned noise into Bengali. hi-IN with codemix
        # still writes English and Hinglish.
        language=Language(config.SARVAM_STT_LANGUAGE),
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
    vad = SileroVADAnalyzer(
        params=VADParams(
            confidence=config.VAD_CONFIDENCE,
            min_volume=config.VAD_MIN_VOLUME,
            start_secs=config.VAD_START_SECS,
            stop_secs=config.VAD_STOP_SECS,
        )
    )
    # A turn starts (and, while the bot speaks, interrupts it) only once the customer
    # has said BARGE_IN_MIN_WORDS words; when the bot is silent one word is enough.
    # Digits and yes/no interrupt at once (ShortAnswerMinWordsStrategy).
    start = [ShortAnswerMinWordsStrategy(min_words=config.BARGE_IN_MIN_WORDS)]
    if config.STT_ENDPOINTING == "manual":
        stop = [
            SpeechTimeoutUserTurnStopStrategy(
                user_speech_timeout=config.USER_SPEECH_TIMEOUT
            )
        ]
    else:
        stop = [ExternalUserTurnStopStrategy()]  # Sarvam's end of speech
    user_params = LLMUserAggregatorParams(
        vad_analyzer=vad,
        user_turn_strategies=UserTurnStrategies(start=start, stop=stop),
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
            NoiseFilter(agent),
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

    latency = TurnLatencyObserver()

    @latency.event_handler("on_latency_breakdown")
    async def on_latency_breakdown(_, breakdown: LatencyBreakdown):
        # Pipecat's breakdown by stage, from the customer's stop (user_silence) to the
        # bot's first audio; the opening line is measured from the call connecting.
        # TurnLatencyObserver keeps the anchor; voice_test checks it agrees with
        # voice_first_audio.
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
        observers=[latency, FirstAudioObserver(agent)],
    )
    agent_step.end_call = worker.stop_when_done

    if "on_client_connected" in getattr(transport, "_event_handlers", {}):
        # Browser connection: speak the opening line as soon as the browser is there,
        # without waiting for the customer to say anything.
        agent_step.client_connected = asyncio.Event()

        @transport.event_handler("on_client_connected")
        async def on_client_connected(*_):
            agent_step.client_connected.set()

    if "on_client_disconnected" in getattr(transport, "_event_handlers", {}):
        # Browser connection: the customer closed the page or pressed End call.
        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(*_):
            await worker.cancel()

    runner = WorkerRunner(handle_sigint=handle_sigint)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        # However the call ended (closing line, hang-up, Ctrl+C), settle the outcome.
        agent._log(type="recording", path=recording_path.as_posix())
        outcome = await agent.finish()
    return outcome
