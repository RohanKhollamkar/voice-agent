"""Stage 1: time to first token for BOT_MODEL and BACKUP_MODEL through OpenRouter.

Sends the same 10 short prompts to each model, one at a time, and reports
median and p95 time to first token plus any errors or empty replies.

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
    """Say whether the model ID exists on OpenRouter and whether reasoning can be set."""
    try:
        listed = {m.id: m for m in (await client.models.list()).data}
    except OpenAIError as error:  # the timing run below still tells us if the ID works
        print(f"  could not list models: {error}")
        return
    if model not in listed:
        print("  MODEL ID NOT FOUND in OpenRouter's model list")
        return
    supported = getattr(listed[model], "supported_parameters", None) or []
    print(
        f"  model ID found; accepts the reasoning setting: {'reasoning' in supported}; "
        f"supports tool calling: {'tools' in supported}"
    )


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
            extra_body={"reasoning": config.LLM_REASONING},
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # OpenRouter streams thinking in a separate `reasoning` field.
            if getattr(delta, "reasoning", None):
                result["thought"] = True
            if delta.content:
                if result["ttft"] is None:
                    result["ttft"] = time.perf_counter() - started
                result["reply"] += delta.content
    except OpenAIError as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


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


async def main(pause: float) -> None:
    client = AsyncOpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,  # a retry would hide an error and inflate the timing
    )
    for model in dict.fromkeys([config.BOT_MODEL, config.BACKUP_MODEL]):
        await run_model(client, model, pause)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="LLM time to first token on OpenRouter."
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=3.0,
        help="seconds between requests, to stay under the free-model limit of 20 a minute",
    )
    asyncio.run(main(parser.parse_args().pause))
