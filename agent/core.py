"""Agent core: customer text in, bot text out. No audio code here.

One Agent is one call. It keeps the conversation, lets the model call tools,
falls back to the backup model on a timeout or error, and writes the transcript
to runs/transcripts/<call_id>.json after every turn.

v1 is the bank's prompt with no guardrails. v2 adds the code guardrails in
agent/guardrails.py: a reply check before anything is spoken, a transfer trigger
on the customer's words, a call timer, a closing line built from the recorded
outcome, and one coherent reply per turn. Dates the customer mentions are resolved
in code (agent/dates.py) and added to their turn as a note.
"""

import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI, OpenAIError

import config
from agent import mock_bank
from agent.dates import date_notes
from agent.guardrails import (
    GOODBYE,
    check_reply,
    closing_line,
    config_numbers,
    numbers_in,
    promise_problems,
    spoken_seconds,
    transfer_trigger,
)
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

# v2: added to the customer's turn once the call passes CALL_CLOSE_WARNING_SECONDS.
TIME_NOTE = (
    "[Note from the system: time is nearly up. If the customer has agreed to something, "
    "confirm it and record it now. If not, tell them a colleague will call back and "
    "record CALLBACK_REQUEST with reason call_time_limit.]"
)
# v2: when the call is ending, or the bot says it has recorded something, but no
# outcome is recorded, the model gets one of these notes, once per reason per call.
NUDGES = {
    "goodbye": (
        "[Note from the system: you said goodbye without calling record_outcome. Call "
        "record_outcome now with what the customer said and agreed to. Say nothing.]"
    ),
    "claimed_record_outcome": (
        "[Note from the system: you told the customer it is recorded, but record_outcome "
        "has not been called. Call record_outcome now with what the customer agreed to. "
        "Say nothing.]"
    ),
    "time_limit": (
        "[Note from the system: the call has reached its time limit. If the customer "
        "agreed to something, call record_outcome now with it. Otherwise record "
        "CALLBACK_REQUEST with reason call_time_limit. Say nothing.]"
    ),
    "hang_up": (
        "[Note from the system: the customer has hung up. If they agreed to something, "
        "call record_outcome now with it. Say nothing.]"
    ),
}
# v2: the bot telling the customer it has done something, by tool. If that tool has
# not run in this call, the model is nudged once to call it (see _claim_nudge).
# "I've noted your request" is the waiver line, said while the call goes on, so it is
# not a claim; "I'll send you a code" is a promise, not a claim.
CLAIMS = {
    "send_otp": re.compile(
        r"\b(?:i've|i have|i|we've|we have)\s+(?:just\s+)?sent\b"
        r"|\b(?:code|otp)\s+(?:has been|have been|was|is)\s+sent\b",
        re.IGNORECASE,
    ),
    "get_account_summary": re.compile(
        r"\b(?:i've|i have|i)\s+(?:just\s+)?(?:checked|looked at|pulled up|reviewed)"
        r"\s+(?:your\s+)?(?:account|details|records|dues)\b",
        re.IGNORECASE,
    ),
    "record_outcome": re.compile(
        r"\b(?:i've|i have|we've|we have|i)\s+(?:now\s+)?recorded\b|\brecorded your\b"
        r"|\b(?:has|have) been recorded\b|\bnoted your (?:promise|payment|commitment)\b",
        re.IGNORECASE,
    ),
}
CLAIM_NOTE = (
    "[Note from the system: you told the customer {what}, but {tool} has not been "
    "called in this call. Call {tool} now, then give the customer your reply again, "
    "based on what it returns.]"
)
CLAIMED_WHAT = {
    "send_otp": "a code has been sent",
    "get_account_summary": "you checked their account",
}


# Some models write their thinking inline, wrapped in <think> tags. An unclosed
# tag means the reply was cut off mid-thought, so everything after it goes too.
THINKING = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)


def strip_thinking(text: str | None) -> str:
    """Remove any thinking text so it is never spoken, logged as speech or re-sent."""
    return THINKING.sub("", text or "").strip()


def now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def spoken_day(day: date, with_iso: bool = False) -> str:
    """ "Friday, 20 November 2026", with " (2026-11-20)" added if asked."""
    text = f"{day:%A}, {day.day} {day:%B %Y}"
    return f"{text} ({day.isoformat()})" if with_iso else text


def upcoming_dates(today: date, days: int = 14) -> str:
    """The next 14 days, one per line, so the model never has to work out which date a
    weekday falls on: "Wednesday, 18 November 2026 (2026-11-18); ..."."""
    return "; ".join(
        spoken_day(today + timedelta(days=ahead), with_iso=True)
        for ahead in range(1, days + 1)
    )


def build_system_prompt(version: str, customer: dict) -> str:
    """The version's prompt file, with the facts of this call.

    v1 gets the account appended, because its prompt says it knows the account. v2's
    prompt has {today}, {upcoming_dates} and {customer_name} filled in and nothing else:
    it gets the account only from get_account_summary, after OTP."""
    prompt_path = PROMPTS_DIR / f"{version}.md"
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(
            f"{prompt_path} is empty; bot version '{version}' is not built yet."
        )
    if version != "v1":
        return (
            prompt.replace("{today}", spoken_day(now().date(), with_iso=True))
            .replace("{upcoming_dates}", upcoming_dates(now().date()))
            .replace("{customer_name}", customer["name"])
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
        clock: str = "spoken",
    ):
        """clock is how the call timer measures time: "spoken" estimates it from the
        words said (text mode, where replies come back in a second), "wall" uses the
        real clock (voice mode)."""
        customer = mock_bank.get_customer(customer_id)
        self.state = CallState(
            call_id=str(uuid.uuid4()),
            customer_id=customer_id,
            bot_version=version,
            started_at=now(),
            guarded=version != "v1",
        )
        self.clock = clock
        self.time_note_sent = False
        self._nudged: set[str] = set()  # the outcome nudges already given
        # Numbers the bot may say (v2 reply check): config, then tool results and the
        # customer's own words as the call goes on.
        self.allowed_numbers = config_numbers()
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

    def elapsed_seconds(self) -> float:
        """How long the call has run, by the agent's clock."""
        if self.clock == "wall":
            return (now() - self.state.started_at).total_seconds()
        return spoken_seconds(
            [e["text"] for e in self.events if e["type"] in ("bot", "customer")]
        )

    async def _reply_to(self, text: str, speaker: str) -> str:
        self._log(type=speaker, text=text)
        started = time.perf_counter()
        content = text
        if speaker == "customer":
            self.state.customer_turns.append(text)
            self.allowed_numbers |= numbers_in(text)
            if self.state.guarded:
                if self._forced_transfer(text):
                    return self._say([self._closing()], started, [], closing=True)
                # Dates the customer mentions, resolved in code: "[Friday = ...]".
                notes = date_notes(text, self.state.started_at.date())
                if notes:
                    content = f"{text} {' '.join(notes)}"
                    self._log(type="date_note", notes=notes)
                late = self.elapsed_seconds() >= config.CALL_CLOSE_WARNING_SECONDS
                if late and not self.time_note_sent:
                    self.time_note_sent = True
                    content = f"{content}\n\n{TIME_NOTE}"
                    self._log(
                        type="timer_note", at_spoken_seconds=self.elapsed_seconds()
                    )
        self.messages.append({"role": "user", "content": content})

        # Each piece is (text, index of the assistant message that carries it).
        pieces: list[tuple[str, int]] = []
        models_used: list[str] = []
        timed_out = (
            self.state.guarded
            and speaker == "customer"
            and self.elapsed_seconds() >= config.CALL_MAX_SECONDS
        )
        if timed_out:
            # v2: the call is out of time. The model gets one chance to record what was
            # agreed; otherwise code records a callback for the time limit.
            await self._nudge("time_limit", pieces, models_used)
            if not self.ended:
                self._record_in_code(
                    "CALLBACK_REQUEST", {"time": None, "reason": "call_time_limit"}
                )
            return self._say(
                self._utterances(pieces), started, models_used, closing=True
            )

        await self._model_rounds(pieces, models_used)
        if self.state.guarded and not self.ended and pieces:
            # v2: the bot claimed an action whose tool has not run (sent a code, checked
            # the account, recorded the outcome), or said goodbye with no outcome
            # recorded. One nudge; see _nudge and _claim_nudge for what is then said.
            claim = self._unbacked_claim(pieces)
            if claim == "record_outcome":
                await self._nudge("claimed_record_outcome", pieces, models_used)
            elif claim:
                await self._claim_nudge(claim, pieces, models_used)
            elif GOODBYE.search(pieces[-1][0]):
                await self._nudge("goodbye", pieces, models_used)

        if not self.state.guarded:  # v1: everything the model said, joined, as before
            bot_text = " ".join(piece for piece, _ in pieces) or FALLBACK_LINE
            return self._say([bot_text], started, models_used)
        return self._say(
            self._utterances(pieces), started, models_used, closing=self.ended
        )

    async def _model_rounds(
        self, pieces: list[tuple[str, int]], models_used: list[str]
    ) -> None:
        """Ask the model, run the tools it calls, and ask again, until it just talks."""
        for _ in range(MAX_TOOL_ROUNDS):
            message, model = await self._ask_model()
            if message is None:  # both models failed
                return
            models_used.append(model)
            if not message.tool_calls:
                self.messages.append({"role": "assistant", "content": message.content})
                if message.content:
                    pieces.append((message.content, len(self.messages) - 1))
                return
            index = self._run_tool_calls(message)
            if message.content:
                pieces.append((message.content, index))
            if self.state.guarded and self.ended:
                return  # record_outcome ends the call; nothing the model says after counts

    def _utterances(self, pieces: list[tuple[str, int]]) -> list[str]:
        """v2: what the bot says this turn, as separate utterances. Text from before and
        after a tool call is never joined into one reply: each piece is its own
        utterance ("I'll send you a code." then "I've sent it, please read it out."),
        checked on its own. Once the outcome is recorded, anything the model said in
        that turn is dropped and the closing line, built in code, is said instead."""
        if self.ended:
            for piece, index in pieces:
                self.messages[index]["content"] = (
                    ""  # not spoken, so not in the history
                )
                self._log(type="discarded_text", text=piece)
            return [self._closing()]
        verified = self.state.otp_verified or not config.ENFORCE_OTP
        utterances = []
        for piece, index in pieces:
            reply, blocks = check_reply(piece, self.allowed_numbers, verified)
            for block in blocks:
                self._log(type="guardrail_block", **block)
            self.messages[index]["content"] = reply  # the history holds what was said
            if reply:
                utterances.append(reply)
        return utterances or [FALLBACK_LINE]

    async def _nudge(
        self, reason: str, pieces: list[tuple[str, int]], models_used: list[str]
    ) -> None:
        """v2: ask the model, once per reason per call, to record the outcome now.
        Anything it says in answer to the note is not spoken unless it records one."""
        if self.ended or reason in self._nudged:
            return
        self._nudged.add(reason)
        self._log(type="outcome_nudge", reason=reason)
        self.messages.append({"role": "user", "content": NUDGES[reason]})
        before = len(pieces)
        await self._model_rounds(pieces, models_used)
        if not self.ended:
            for piece, index in pieces[before:]:
                self.messages[index]["content"] = ""
                self._log(type="discarded_text", text=piece)
            del pieces[before:]

    def _unbacked_claim(self, pieces: list[tuple[str, int]]) -> str | None:
        """v2: the first tool the bot said this turn it had used, but which has not run
        in this call. Each tool is nudged for at most once per call."""
        for tool, pattern in CLAIMS.items():
            done = (
                self.state.outcome_type is not None
                if tool == "record_outcome"
                else tool in self.state.tools_done
            )
            if done or f"claimed_{tool}" in self._nudged:
                continue
            if any(pattern.search(piece) for piece, _ in pieces):
                return tool
        return None

    async def _claim_nudge(
        self, tool: str, pieces: list[tuple[str, int]], models_used: list[str]
    ) -> None:
        """v2: the bot said it sent a code or checked the account without calling the
        tool. Ask the model once to call it. If it does and replies again, the new
        reply replaces the claim; if it does not call it, the claim stands and the
        answer to the note is not spoken (the verify_otp and figure checks still
        apply)."""
        self._nudged.add(f"claimed_{tool}")
        self._log(type="action_nudge", tool=tool)
        note = CLAIM_NOTE.format(what=CLAIMED_WHAT[tool], tool=tool)
        self.messages.append({"role": "user", "content": note})
        before = len(pieces)
        await self._model_rounds(pieces, models_used)
        called = tool in self.state.tools_done
        replaced = called and len(pieces) > before
        dropped = pieces[:before] if replaced else pieces[before:]
        for piece, index in dropped:
            self.messages[index]["content"] = ""
            self._log(type="discarded_text", text=piece)
        if replaced:
            del pieces[:before]
        else:
            del pieces[before:]

    def _forced_transfer(self, customer_text: str) -> bool:
        """v2: when the customer's words call for a transfer, record it in code,
        without asking the model."""
        reason = transfer_trigger(customer_text)
        if not reason:
            return False
        self._record_in_code("TRANSFER_TO_HUMAN", {"reason": reason})
        return self.ended

    def _record_in_code(self, outcome_type: str, details: dict) -> None:
        arguments = {"outcome_type": outcome_type, "details": details}
        result = run_tool(self.state, "record_outcome", arguments)
        self._log(
            type="tool_call",
            name="record_outcome",
            arguments=arguments,
            result=result,
            recorded_by="guardrail",
            latency_ms=0,
        )

    def _closing(self) -> str:
        return closing_line(
            self.state.outcome_type,
            self.state.outcome_details,
            self.state.follow_ups or [],
            self.state.started_at.date(),
        )

    def _say(
        self,
        utterances: list[str],
        started: float,
        models_used: list[str],
        closing: bool = False,
    ) -> str:
        """Log each utterance as its own bot turn and save the transcript. Returns the
        utterances one per line, so a caller can print or speak them separately."""
        for number, text in enumerate(utterances, start=1):
            last = number == len(utterances)
            extra = {"closing": True} if closing and last else {}
            if last:  # the customer's whole wait: every model call and tool in the turn
                extra["latency_ms"] = round((time.perf_counter() - started) * 1000)
            self._log(type="bot", text=text, models=models_used, **extra)
        self._save_transcript()
        return "\n".join(utterances)

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

    def _run_tool_calls(self, message) -> int:
        """Run every tool the model asked for and add the results to the conversation.
        Returns the position in the history of the assistant message that asked."""
        index = len(self.messages)
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
            self.allowed_numbers |= numbers_in(json.dumps(result))
        return index

    async def finish(self) -> dict:
        """End the call: settle the outcome, save it, POST it. Returns the outcome."""
        if self.outcome is not None:
            return self.outcome

        captured_by = "tool_call"
        if self.state.outcome_type is None and self.state.guarded:
            # v2: the customer has gone with no outcome recorded. One nudge to the
            # model; nothing it says is spoken, the call is over.
            pieces: list[tuple[str, int]] = []
            await self._nudge("hang_up", pieces, [])
            for piece, index in pieces:
                self.messages[index]["content"] = ""
                self._log(type="discarded_text", text=piece)
        if self.state.outcome_type is None:
            # The bot never called record_outcome, so read the outcome off the transcript.
            captured_by = "post_call_extraction"
            outcome_type, details, follow_ups, error = await extract_outcome(
                self.client, self._transcript_text(), today=f"{now():%Y-%m-%d}"
            )
            self._log(
                type="post_call_extraction",
                model=config.JUDGE_MODEL,
                outcome_type=outcome_type,
                details=details,
                follow_ups=follow_ups,
                error=error,
            )
            if self.state.guarded:
                outcome_type, details, follow_ups = self._supported(
                    outcome_type, details, follow_ups
                )
            self.state.outcome_type, self.state.outcome_details = outcome_type, details
            self.state.follow_ups = follow_ups

        self.outcome = build_outcome(
            call_id=self.state.call_id,
            customer_id=self.state.customer_id,
            bot_version=self.state.bot_version,
            started_at=self.state.started_at,
            ended_at=now(),
            otp_verified=self.state.otp_verified,
            outcome_type=self.state.outcome_type,
            details=self.state.outcome_details,
            follow_ups=self.state.follow_ups,
            captured_by=captured_by,
            transcript_path=self.transcript_path.as_posix(),
        )
        errors = validate_outcome(self.outcome)
        save_outcome(self.outcome)
        self.webhook = await post_to_webhook(self.outcome)
        self._save_transcript(outcome_errors=errors, webhook=self.webhook)
        return self.outcome

    def _supported(
        self, outcome_type: str | None, details: dict | None, follow_ups: list
    ) -> tuple[str | None, dict | None, list]:
        """v2: the post-call extraction may only produce a promise to pay that the
        customer's own words support (date and amount). Otherwise the call has no
        outcome, flagged in the transcript, unless it ran out of time, in which case it
        is a callback for the time limit. A promise is never invented."""
        if outcome_type != "PROMISE_TO_PAY":
            return outcome_type, details, follow_ups
        customer = mock_bank.get_customer(self.state.customer_id)
        problems = [
            problem
            for problem in promise_problems(
                details,
                self.state.customer_turns,
                customer,
                self.state.started_at.date(),
            )
            if "last reply" not in problem  # a hang-up after the promise still counts
        ]
        if not problems:
            return outcome_type, details, follow_ups
        self._log(type="extraction_rejected", details=details, problems=problems)
        if self.elapsed_seconds() >= config.CALL_MAX_SECONDS:
            return "CALLBACK_REQUEST", {"time": None, "reason": "call_time_limit"}, []
        return None, None, []

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
            "guardrails": self.state.guarded,
            "clock": self.clock,
            "started_at": self.state.started_at.isoformat(timespec="seconds"),
            "events": self.events,
            "outcome": self.outcome,
            **extra,
        }
        self.transcript_path.write_text(
            json.dumps(transcript, indent=2, ensure_ascii=False), encoding="utf-8"
        )
