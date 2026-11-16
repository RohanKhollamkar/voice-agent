"""Agent core: customer text in, bot text out. No audio code here.

One Agent is one call. It keeps the conversation, lets the model call tools,
falls back to the backup model on a timeout or error, and writes the transcript
to runs/transcripts/<call_id>.json after every turn.
"""

import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI, OpenAIError

import config
from agent import mock_bank
from agent.outcome import (
    build_outcome,
    extract_outcome,
    post_to_webhook,
    save_outcome,
    validate_outcome,
)
from agent.tools import CallState, run_tool, tool_schemas

PROMPTS_DIR = Path(__file__).parent / "prompts"

# The bot speaks first on an outbound call, so the conversation opens with this
# in place of customer speech.
CALL_CONNECTED = "[The customer has answered the call.]"

# Said if both models fail or the model loops on tools, so the call never crashes.
FALLBACK_LINE = "I'm sorry, I'm having trouble on my side. Could you say that again?"

MAX_TOOL_ROUNDS = 5  # model -> tools -> model ... per customer turn


# Some models write their thinking inline, wrapped in <think> tags. An unclosed
# tag means the reply was cut off mid-thought, so everything after it goes too.
THINKING = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)


def strip_thinking(text: str | None) -> str:
    """Remove any thinking text so it is never spoken, logged as speech or re-sent."""
    return THINKING.sub("", text or "").strip()


def now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def build_system_prompt(version: str, customer: dict) -> str:
    """The version's prompt file, unchanged, followed by the facts of this call."""
    prompt_path = PROMPTS_DIR / f"{version}.md"
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(
            f"{prompt_path} is empty; bot version '{version}' is not built yet."
        )

    context = [
        "Call context:",
        f"- Today is {now():%A, %Y-%m-%d}.",
        f"- You are calling {customer['name']}.",
    ]
    if version == "v1":
        # The bank's prompt says the bot "knows everything about the customer's
        # account", so v1 is handed the account up front, with no OTP step.
        context += [
            f"- Outstanding balance: ₹{customer['outstanding_balance']}.",
            f"- Minimum due: ₹{customer['minimum_due']}.",
            f"- Days past due: {customer['days_past_due']}.",
        ]
    return prompt + "\n\n" + "\n".join(context)


class Agent:
    """One call with one customer."""

    def __init__(
        self,
        customer_id: str,
        version: str = config.BOT_VERSION,
        client: AsyncOpenAI | None = None,
    ):
        customer = mock_bank.get_customer(customer_id)
        self.state = CallState(
            call_id=str(uuid.uuid4()),
            customer_id=customer_id,
            bot_version=version,
            started_at=now(),
        )
        self.client = client or AsyncOpenAI(
            api_key=config.NVIDIA_API_KEY,
            base_url=config.NVIDIA_BASE_URL,
            max_retries=0,  # our own fallback to the backup model handles failures
        )
        self.messages: list[dict] = [
            {"role": "system", "content": build_system_prompt(version, customer)}
        ]
        self.events: list[dict] = []  # the transcript: turns, tool calls, errors
        self.outcome: dict | None = None
        self.webhook: dict | None = None  # result of the webhook POST, set by finish()
        self.transcript_path = (
            config.RUNS_DIR / "transcripts" / f"{self.state.call_id}.json"
        )

    @property
    def ended(self) -> bool:
        """True once an outcome is recorded; the bot's next line is its goodbye."""
        return self.state.outcome_type is not None

    async def start(self) -> str:
        """Open the call. Returns the bot's first line."""
        return await self._reply_to(CALL_CONNECTED, speaker="call_connected")

    async def respond(self, customer_text: str) -> str:
        """Take what the customer said and return what the bot says back."""
        return await self._reply_to(customer_text, speaker="customer")

    async def _reply_to(self, text: str, speaker: str) -> str:
        self._log(type=speaker, text=text)
        self.messages.append({"role": "user", "content": text})

        started = time.perf_counter()
        spoken: list[str] = []
        models_used: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            message, model = await self._ask_model()
            if message is None:  # both models failed
                break
            models_used.append(model)
            if message.content:
                spoken.append(message.content)
            if not message.tool_calls:
                self.messages.append({"role": "assistant", "content": message.content})
                break
            self._run_tool_calls(message)

        bot_text = " ".join(spoken) or FALLBACK_LINE
        # latency_ms is the customer's whole wait: every model call and tool in the turn.
        self._log(
            type="bot",
            text=bot_text,
            models=models_used,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        self._save_transcript()
        return bot_text

    async def _ask_model(self) -> tuple[object | None, str | None]:
        """One model call: BOT_MODEL first, BACKUP_MODEL on a timeout, error or empty reply."""
        for model in (config.BOT_MODEL, config.BACKUP_MODEL):
            started = time.perf_counter()
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=self.messages,
                    tools=tool_schemas(self.state.bot_version),
                    timeout=config.LLM_TIMEOUT_SECONDS,
                    extra_body=config.LLM_EXTRA_BODY,
                )
                message = response.choices[0].message if response.choices else None
                if message:
                    # Thinking sent in its own field is ignored; inline thinking is cut here.
                    message.content = strip_thinking(message.content)
                if message and (message.content or message.tool_calls):
                    self._log(
                        type="llm_call",
                        model=model,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                    )
                    return message, model
                error = "empty reply"
            except OpenAIError as failure:
                error = f"{type(failure).__name__}: {failure}"
            self._log(
                type="llm_error",
                model=model,
                error=error,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        return None, None

    def _run_tool_calls(self, message) -> None:
        """Run every tool the model asked for and add the results to the conversation."""
        self.messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                ],
            }
        )
        for call in message.tool_calls:
            started = time.perf_counter()
            try:
                arguments = json.loads(call.function.arguments or "{}")
                result = run_tool(self.state, call.function.name, arguments)
            except json.JSONDecodeError:
                arguments = call.function.arguments
                result = {"error": "Tool arguments were not valid JSON."}
            self._log(
                type="tool_call",
                name=call.function.name,
                arguments=arguments,
                result=result,
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
            self.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )

    async def finish(self) -> dict:
        """End the call: settle the outcome, save it, POST it. Returns the outcome."""
        if self.outcome is not None:
            return self.outcome

        captured_by = "tool_call"
        if self.state.outcome_type is None:
            # The bot never called record_outcome, so read the outcome off the transcript.
            captured_by = "post_call_extraction"
            outcome_type, details, error = await extract_outcome(
                self.client, self._transcript_text(), today=f"{now():%Y-%m-%d}"
            )
            self.state.outcome_type, self.state.outcome_details = outcome_type, details
            self._log(
                type="post_call_extraction",
                model=config.JUDGE_MODEL,
                outcome_type=outcome_type,
                details=details,
                error=error,
            )

        self.outcome = build_outcome(
            call_id=self.state.call_id,
            customer_id=self.state.customer_id,
            bot_version=self.state.bot_version,
            started_at=self.state.started_at,
            ended_at=now(),
            otp_verified=self.state.otp_verified,
            outcome_type=self.state.outcome_type,
            details=self.state.outcome_details,
            captured_by=captured_by,
            transcript_path=self.transcript_path.as_posix(),
        )
        errors = validate_outcome(self.outcome)
        save_outcome(self.outcome)
        self.webhook = await post_to_webhook(self.outcome)
        self._save_transcript(outcome_errors=errors, webhook=self.webhook)
        return self.outcome

    def _transcript_text(self) -> str:
        """The spoken turns only, as plain lines, for the post-call extraction."""
        names = {"customer": "Customer", "bot": "Bot"}
        return "\n".join(
            f"{names[event['type']]}: {event['text']}"
            for event in self.events
            if event["type"] in names
        )

    def _log(self, **event) -> None:
        elapsed = (now() - self.state.started_at).total_seconds()
        self.events.append({"at_seconds": round(elapsed, 2), **event})

    def _save_transcript(self, **extra) -> None:
        """Rewrite the transcript file. Called every turn so a crash loses nothing."""
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript = {
            "call_id": self.state.call_id,
            "customer_id": self.state.customer_id,
            "bot_version": self.state.bot_version,
            "bot_model": config.BOT_MODEL,
            "backup_model": config.BACKUP_MODEL,
            "enforce_otp": config.ENFORCE_OTP,
            "started_at": self.state.started_at.isoformat(timespec="seconds"),
            "events": self.events,
            "outcome": self.outcome,
            **extra,
        }
        self.transcript_path.write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8"
        )
