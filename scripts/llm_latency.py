"""Stage 1: time to first token for BOT_MODEL, BACKUP_MODEL and JUDGE_MODEL on the NVIDIA API.

Sends the same 10 short prompts to each model, one at a time, and reports
median and p95 time to first token plus any errors or empty replies. Then sends
one prompt with a tool definition to confirm the model returns a proper tool call.

Run from the repo root:
    python -m scripts.llm_latency
"""

import argparse
import asyncio
import math
import statistics
import time

from openai import AsyncOpenAI, OpenAIError

import config

SYSTEM_PROMPT = "You are a polite assistant. Reply in one short English sentence."

PROMPTS = [
    "Hello, who is this?",
    "I already paid yesterday.",
    "Can you call me back later?",
    "How much is the late fee?",
    "Main abhi busy hoon, baad mein call karo.",
    "Maine payment kal UPI se kar diya tha.",
    "What is the interest rate on my card?",
    "I lost my job last month.",
    "Can you waive the late fee?",
    "Okay, I will pay on Friday.",
]

TIMEOUT_SECONDS = 30


async def check_model(client: AsyncOpenAI, model: str) -> None:
    """Say whether the model ID exists in the NVIDIA API's model list."""
    try:
        listed = {m.id: m for m in (await client.models.list()).data}
    except OpenAIError as error:  # the timing run below still tells us if the ID works
        print(f"  could not list models: {error}")
        return
    if model not in listed:
        print("  MODEL ID NOT FOUND in the NVIDIA API's model list")
        return
    print("  model ID found in the NVIDIA API's model list")


async def time_one(client: AsyncOpenAI, model: str, prompt: str) -> dict:
    """Send one prompt and time the first answer token."""
    result = {"ttft": None, "reply": "", "thought": False, "error": None}
    started = time.perf_counter()
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
            extra_body=config.LLM_EXTRA_BODY,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # NVIDIA streams thinking in a separate `reasoning_content` field.
            if getattr(delta, "reasoning_content", None):
                result["thought"] = True
            if delta.content:
                if result["ttft"] is None:
                    result["ttft"] = time.perf_counter() - started
                result["reply"] += delta.content
    except OpenAIError as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


TOOL_PROMPT = "Please send the OTP to my phone now."
TOOL = {
    "type": "function",
    "function": {
        "name": "send_otp",
        "description": "Send a one-time password to the customer's registered phone.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


async def check_tool_call(client: AsyncOpenAI, model: str) -> None:
    """Send one prompt with a tool defined and say whether a proper tool call came back."""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": TOOL_PROMPT},
            ],
            tools=[TOOL],
            extra_body=config.LLM_EXTRA_BODY,
        )
    except OpenAIError as error:
        print(f"  tool call: ERROR  {type(error).__name__}: {str(error)[:150]}")
        return
    message = response.choices[0].message if response.choices else None
    calls = (message.tool_calls if message else None) or []
    if calls and calls[0].function.name == "send_otp":
        print("  tool call: OK, the model called send_otp")
    else:
        said = (message.content or "").strip()[:80] if message else ""
        print(f"  tool call: NOT MADE, the model replied in text instead: {said!r}")


def p95(values: list[float]) -> float:
    """Nearest-rank 95th percentile. With 10 samples this is the slowest one."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def run_model(client: AsyncOpenAI, model: str, pause: float) -> None:
    print(f"\n== {model} ==")
    await check_model(client, model)

    results = []
    for number, prompt in enumerate(PROMPTS, start=1):
        result = await time_one(client, model, prompt)
        results.append(result)
        if result["error"]:
            print(f"  {number:2}. ERROR  {result['error'][:150]}")
        elif not result["reply"].strip():
            print(f"  {number:2}. EMPTY REPLY")
        else:
            print(
                f"  {number:2}. {result['ttft']:.2f}s  {result['reply'].strip()[:70]}"
            )
        await asyncio.sleep(pause)

    times = [r["ttft"] for r in results if r["ttft"] is not None]
    errors = sum(1 for r in results if r["error"])
    empty = sum(1 for r in results if not r["error"] and not r["reply"].strip())
    thought = sum(1 for r in results if r["thought"])
    if times:
        print(
            f"  time to first token: median {statistics.median(times):.2f}s, "
            f"p95 {p95(times):.2f}s over {len(times)} replies"
        )
    print(
        f"  errors: {errors}, empty replies: {empty}, replies that still sent thinking: {thought}"
    )
    await check_tool_call(client, model)


async def main(pause: float) -> None:
    client = AsyncOpenAI(
        api_key=config.NVIDIA_API_KEY,
        base_url=config.NVIDIA_BASE_URL,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,  # a retry would hide an error and inflate the timing
    )
    for model in dict.fromkeys(
        [config.BOT_MODEL, config.BACKUP_MODEL, config.JUDGE_MODEL]
    ):
        await run_model(client, model, pause)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LLM time to first token on the NVIDIA API."
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.5,
        help="seconds between requests, to stay under NVIDIA's free limit of about 40 a minute",
    )
    asyncio.run(main(parser.parse_args().pause))
