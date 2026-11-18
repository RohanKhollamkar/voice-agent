"""Start a voice call on this computer's mic and speaker.

Run from the repo root, with headphones (there is no echo cancellation, so on
speakers the bot hears itself and interrupts):
    python -m voice.call --customer C001 --version v2

The call ends when the bot records the outcome and says goodbye, or on Ctrl+C.
"""

import argparse
import asyncio
import json

import config
from agent import mock_bank
from voice.pipeline import run_call


async def main(customer_id: str, version: str) -> None:
    customer = mock_bank.get_customer(customer_id)
    print(f"Calling {customer['name']} ({customer_id}) with bot {version}.")
    if version != "v1":
        print(f"Mock OTP for this customer: {customer['otp']}.")
    print("Speak after the bot's first line. Ctrl+C to hang up.\n")
    outcome = await run_call(customer_id, version)
    print("\nOutcome:")
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    print(f"Transcript: {outcome['transcript_path']}")
    print(
        f"Recording: {config.RUNS_DIR / 'recordings' / (outcome['call_id'] + '.wav')}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice call with the collections bot.")
    parser.add_argument("--customer", default="C001", choices=list(mock_bank.CUSTOMERS))
    parser.add_argument("--version", default=config.BOT_VERSION, choices=["v1", "v2"])
    args = parser.parse_args()
    asyncio.run(main(args.customer, args.version))
