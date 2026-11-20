"""Run a voice call without a microphone, and report latency per stage.

A fake transport replaces the mic and speaker. The customer's lines are spoken by
a Sarvam voice (cached on disk after the first run) and played into the real pipeline (Sarvam speech-to-
text, the agent, the reply check, the normaliser, speech) in real time; the bot's
audio is "played" in real time too, so turn-taking and barge-in behave as on a call.
Each customer line waits until the bot has finished its reply, except with
--barge-in, where the third line is spoken over the bot.

Run from the repo root:
    python -m scripts.voice_test
    python -m scripts.voice_test --barge-in
    python -m scripts.voice_test --noise 600     (background noise under everything)
    STT_ENDPOINTING=manual python -m scripts.voice_test    (try a turn-taking setting)

It prints the call, its outcome and a latency table, and writes the transcript and
WAV recording as any voice call does.
"""

import argparse
import asyncio
import base64
import hashlib
import io
import json
import statistics
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from loguru import logger
from num2words import num2words
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, StartFrame
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams

import config
from agent import mock_bank
from voice.pipeline import run_call

RATE = 16000  # customer audio sample rate
CHUNK = 320  # 20 ms frames
CUSTOMER_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # ElevenLabs premade "George"
QUIET_SECONDS = 1.3  # the bot counts as finished after this much silence
MAX_CALL_SECONDS = 240


class Noise:
    """Background noise mixed into everything the customer's mic sends: a steady low
    rumble with a 50 Hz hum, and every few seconds a short louder burst (a clatter, a
    voice in the next room). Off unless --noise gives a level (RMS, 16-bit)."""

    level = 0.0
    _rng = np.random.default_rng(7)
    _brown = 0.0
    _t = 0

    @classmethod
    def mix(cls, chunk: bytes) -> bytes:
        if not cls.level:
            return chunk
        n = len(chunk) // 2
        white = cls._rng.normal(0, 1, n)
        brown = np.empty(n)
        for i, w in enumerate(white):  # integrate white noise: a low rumble
            cls._brown = 0.98 * cls._brown + w
            brown[i] = cls._brown
        brown *= cls.level / (np.std(brown) or 1)
        t = (cls._t + np.arange(n)) / RATE
        hum = 0.4 * cls.level * np.sin(2 * np.pi * 50 * t)
        noise = brown + hum
        if (cls._t // RATE) % 4 == 3 and (cls._t % RATE) < RATE * 0.4:
            noise += cls._rng.normal(0, 4 * cls.level, n)  # a 0.4 s burst every 4 s
        cls._t += n
        samples = np.frombuffer(chunk, dtype=np.int16).astype(float) + noise
        return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


class Call:
    """What the fake transport has seen so far."""

    bot_spoke_at = 0.0  # last time the bot's audio held speech (not idle silence)
    bot_reply_started = 0.0  # when the current run of bot speech began
    customer_busy = False
    customer_done_at = 0.0


class CustomerInput(BaseInputTransport):
    """Plays queued customer audio in real time, and silence in between."""

    def __init__(self, params: TransportParams, lines: asyncio.Queue):
        super().__init__(params)
        self._lines = lines

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self.set_transport_ready(frame)
        self._feed_task = self.create_task(self._feed())

    async def stop(self, frame):
        await self.cancel_task(self._feed_task)
        await super().stop(frame)

    async def cancel(self, frame):
        await self.cancel_task(self._feed_task)
        await super().cancel(frame)

    async def _feed(self):
        silence, pending = b"\0" * (CHUNK * 2), b""
        while True:
            if not pending and not self._lines.empty():
                pending = self._lines.get_nowait()
            if not pending and self._lines.empty() and Call.customer_busy:
                Call.customer_busy, Call.customer_done_at = False, time.monotonic()
            chunk, pending = (
                (pending[: CHUNK * 2], pending[CHUNK * 2 :])
                if pending
                else (silence, b"")
            )
            frame = InputAudioRawFrame(
                audio=Noise.mix(chunk.ljust(CHUNK * 2, b"\0")),
                sample_rate=RATE,
                num_channels=1,
            )
            await self.push_audio_frame(frame)
            await asyncio.sleep(0.02)


class BotOutput(BaseOutputTransport):
    """Takes the bot's audio at playback speed and notes when it holds speech."""

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        samples = np.frombuffer(frame.audio, dtype=np.int16).astype(float)
        if (
            samples.size and np.sqrt(np.mean(samples**2)) > 200
        ):  # speech, not idle silence
            now = time.monotonic()
            if now - Call.bot_spoke_at > 0.6:
                Call.bot_reply_started = now
            Call.bot_spoke_at = now
        await asyncio.sleep(len(frame.audio) / 2 / frame.sample_rate)
        return True


class FakeTransport(BaseTransport):
    def __init__(self, lines: asyncio.Queue):
        super().__init__()
        params = TransportParams(audio_in_enabled=True, audio_out_enabled=True)
        self._input, self._output = CustomerInput(params, lines), BotOutput(params)

    def input(self):
        return self._input

    def output(self):
        return self._output


CACHE_DIR = config.RUNS_DIR / "voice_test_cache"


def speech(text: str) -> bytes:
    """The customer's line as 16 kHz audio, synthesised once and then reused from
    runs/voice_test_cache/, so reruns cost no speech credits. Sarvam by default, or
    ElevenLabs with TTS_PROVIDER=elevenlabs (falling back to Sarvam if it refuses: its
    free plan has a monthly character quota)."""
    provider = "elevenlabs" if config.TTS_PROVIDER == "elevenlabs" else "sarvam"
    key = hashlib.sha256(f"{provider}|{text}".encode()).hexdigest()[:20]
    cached = CACHE_DIR / f"{key}.pcm"
    if cached.exists():
        return cached.read_bytes()
    if provider == "elevenlabs":
        try:
            audio = elevenlabs_speech(text)
        except httpx.HTTPStatusError as error:
            print(f"  (ElevenLabs refused: {error.response.status_code}; using Sarvam)")
            audio = sarvam_speech(text)
    else:
        audio = sarvam_speech(text)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(audio)
    return audio


def sarvam_speech(text: str) -> bytes:
    from sarvamai import SarvamAI

    response = SarvamAI(
        api_subscription_key=config.SARVAM_API_KEY
    ).text_to_speech.convert(
        text=text,
        target_language_code="en-IN",
        model="bulbul:v3",
        speaker="aditya",
        speech_sample_rate=RATE,
    )
    with wave.open(io.BytesIO(base64.b64decode(response.audios[0]))) as file:
        return file.readframes(file.getnframes())


def elevenlabs_speech(text: str) -> bytes:
    response = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{CUSTOMER_VOICE}?output_format=pcm_16000",
        headers={"xi-api-key": config.ELEVENLABS_API_KEY},
        json={"text": text, "model_id": config.ELEVENLABS_MODEL},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


async def bot_finished_reply():
    """Wait until the customer's last line has played, the bot has replied after it,
    and the bot has gone quiet."""
    while Call.customer_busy:
        await asyncio.sleep(0.05)
    while Call.bot_reply_started <= Call.customer_done_at - 0.2:
        await asyncio.sleep(0.05)
    while time.monotonic() - Call.bot_spoke_at < QUIET_SECONDS:
        await asyncio.sleep(0.1)


async def bot_talking_for(seconds: float):
    """Wait until the bot has been speaking for this long (to talk over it)."""
    start = time.monotonic()
    while not (
        Call.bot_reply_started > start - 0.5
        and time.monotonic() - Call.bot_reply_started > seconds
        and time.monotonic() - Call.bot_spoke_at < 0.3
    ):
        await asyncio.sleep(0.05)


async def customer(
    lines: asyncio.Queue,
    script: list[tuple[str, str]],
    started: float,
    otp_pause: float,
):
    for text, when in script:
        if otp_pause and text.startswith("OTP:"):
            # Read the code in two halves with a pause, as people do.
            digits = text.removeprefix("OTP:").split()
            text = " ".join(digits[:3]) + " ... " + " ".join(digits[3:])
            gap = b"\0" * int(RATE * otp_pause) * 2
            audio = (
                speech(" ".join(digits[:3]) + ".")
                + gap
                + speech(" ".join(digits[3:]) + ".")
            )
        else:
            text = text.removeprefix("OTP:")
            audio = speech(text)
        await (bot_talking_for(1.5) if when == "over the bot" else bot_finished_reply())
        print(
            f"  {time.monotonic() - started:5.1f}s  customer ({when}): {text}",
            flush=True,
        )
        Call.customer_busy = True
        await lines.put(audio + b"\0" * RATE * 2)  # the line, then a second of silence


def latency_rows(transcript: dict) -> list[dict]:
    """One row per answered customer turn, in seconds. "total" is the time to the bot's
    first audio, which is the holding line when one was said (ack = 1)."""
    turns: list[dict] = []
    for event in transcript["events"]:
        if event["type"] == "customer":
            turns.append({"models": [], "agent": None, "latency": None, "ack": 0})
        elif not turns:
            continue  # the opening line, before the customer has said anything
        elif event["type"] == "llm_call":
            turns[-1]["models"].append(event["latency_ms"] / 1000)
        elif event["type"] == "voice_agent_time" and turns[-1]["agent"] is None:
            turns[-1]["agent"] = event["seconds"]
        elif event["type"] == "voice_ack":
            turns[-1]["ack"] = 1
        elif event["type"] == "voice_latency" and turns[-1]["latency"] is None:
            turns[-1]["latency"] = event
    rows = []
    for turn in turns:
        if turn["latency"] is None:
            continue  # the turn was never answered (the call ended)
        parts = turn["latency"]["parts"]
        rows.append(
            {
                "end of speech": parts.get("endpointing wait", 0),
                "speech-to-text": parts.get("transcription", 0),
                "turn detection": parts.get("turn detection", 0),
                "agent": turn["agent"] or 0,
                "first model call": turn["models"][0] if turn["models"] else 0,
                "model calls": len(turn["models"]),
                "ack": turn["ack"],
                "speech": parts.get("speech synthesis", 0),
                "total": turn["latency"]["total_seconds"],
            }
        )
    return rows


def print_latency(rows: list[dict]) -> None:
    if not rows:
        print("No customer turn was answered.")
        return
    columns = list(rows[0])
    print(
        "\nLatency per turn, seconds from the end of the customer's speech to the bot's audio"
    )
    print("  " + "  ".join(f"{c:>16}" for c in columns))
    for row in rows:
        print(
            "  "
            + "  ".join(
                f"{row[c]:>16}" if c in ("model calls", "ack") else f"{row[c]:>16.2f}"
                for c in columns
            )
        )
    medians = {c: statistics.median(r[c] for r in rows) for c in columns}
    print("  " + "  ".join(f"{medians[c]:>16.2f}" for c in columns) + "   (median)")
    print(
        "  agent = model calls and tools; with no streaming, the first model call's time is"
        " its time to first token."
    )


async def main(
    customer_id: str, version: str, barge_in: bool, otp_pause: float
) -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    otp = mock_bank.get_customer(customer_id)["otp"]
    script = [
        ("Yes, speaking.", "after the bot"),
        ("OTP:" + " ".join(num2words(int(d)) for d in otp), "after the bot"),
        (
            "I'll pay the full amount on Friday.",
            "over the bot" if barge_in else "after the bot",
        ),
        ("Yes, that's right.", "after the bot"),
        ("Yes, that's right.", "after the bot"),  # if the bot asks to confirm again
    ]
    lines: asyncio.Queue = asyncio.Queue()
    started = time.monotonic()
    talking = asyncio.create_task(customer(lines, script, started, otp_pause))
    try:
        outcome = await asyncio.wait_for(
            run_call(customer_id, version, transport=FakeTransport(lines)),
            MAX_CALL_SECONDS,
        )
    finally:
        talking.cancel()
    transcript = json.loads(
        Path(outcome["transcript_path"]).read_text(encoding="utf-8")
    )
    print("\nThe call:")
    for event in transcript["events"]:
        if event["type"] in ("bot", "customer"):
            print(f"  {event['at_seconds']:5.1f}s  {event['type']}: {event['text']}")
    details = (
        outcome["details"].get(outcome["outcome_type"])
        if outcome["outcome_type"]
        else None
    )
    print(f"\nOutcome: {outcome['outcome_type']} {details} ({outcome['captured_by']})")
    shown = (
        "ignored_noise",
        "voice_turn_joined",
        "discarded_text",
        "voice_code_joined",
    )
    notes = [e for e in transcript["events"] if e["type"] in shown]
    for event in notes:
        extra = event.get("text") or event.get("parts")
        print(f"  {event['at_seconds']:5.1f}s  {event['type']}: {extra}")
    print_latency(latency_rows(transcript))
    print(f"\nTranscript: {outcome['transcript_path']}")
    print(f"Recording: runs/recordings/{outcome['call_id']}.wav")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A voice call with a scripted customer."
    )
    parser.add_argument("--customer", default="C001", choices=list(mock_bank.CUSTOMERS))
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    parser.add_argument(
        "--barge-in", action="store_true", help="speak the third line over the bot"
    )
    parser.add_argument(
        "--otp-pause",
        type=float,
        default=0,
        help="pause this many seconds in the middle of reading out the OTP",
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=0,
        help="mix background noise at this level (RMS, 16-bit; 600 is a busy room)",
    )
    args = parser.parse_args()
    Noise.level = args.noise
    asyncio.run(main(args.customer, args.version, args.barge_in, args.otp_pause))
