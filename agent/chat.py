"""Typed conversation with the bot, for testing without audio.

Run from the repo root:
    python -m agent.chat --customer C001 --version v1

You play the customer. Type /end (or press Ctrl+D) to hang up.
"""

import argparse
import asyncio
import json

import config
from agent import mock_bank
from agent.core import Agent


async def main(customer_id: str, version: str) -> None:
    agent = Agent(customer_id, version)
    customer = mock_bank.get_customer(customer_id)
    print(f"Calling {customer['name']} ({customer_id}) with bot {version}.")
    if version != "v1":  # v1 has no OTP step
        print(f"Mock OTP for this customer: {customer['otp']}.")
    print("Type /end to hang up.\n")

    print(f"Bot: {await agent.start()}")
    while not agent.ended:
        try:
            customer_text = input("You: ").strip()
        except EOFError:
            break
        if customer_text == "/end":
            break
        if customer_text:
            print(f"Bot: {await agent.respond(customer_text)}")

    outcome = await agent.finish()
    print("\nOutcome:")
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    print(f"\nWebhook: {agent.webhook}")
    print(f"Transcript: {agent.transcript_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Typed call with the collections bot.")
    parser.add_argument("--customer", default="C001", choices=list(mock_bank.CUSTOMERS))
    parser.add_argument("--version", default=config.BOT_VERSION, choices=["v1", "v2"])
    args = parser.parse_args()
    asyncio.run(main(args.customer, args.version))
