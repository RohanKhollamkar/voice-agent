"""Retry a model request when the provider rate-limits it.

The judge, the post-call extraction and the simulated customer all use the same
model, and eval runs go side by side, so they can hit the provider's per-model
limit. A short wait and a retry is enough; anything other than a rate limit is
raised at once.
"""

import asyncio
from collections.abc import Awaitable, Callable

from openai import RateLimitError

import config


async def retry_on_rate_limit[T](make_request: Callable[[], Awaitable[T]]) -> T:
    """Await make_request(), waiting and retrying while the provider answers 429."""
    for wait in config.RATE_LIMIT_WAITS_SECONDS:
        try:
            return await make_request()
        except RateLimitError:
            await asyncio.sleep(wait)
    return await make_request()  # the last try: a rate limit now is raised
