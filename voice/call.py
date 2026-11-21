"""Start a voice call with the collections bot.

Run from the repo root:
    python -m voice.call --customer C001 --version v2
    python -m voice.call --echo half-duplex      laptop speakers, no headphones
    python -m voice.call --echo browser          then open http://localhost:7860

--echo picks how the bot avoids hearing itself:
  none          the local mic and speaker as they are. Use headphones: on speakers the
                bot hears its own voice and interrupts itself.
  half-duplex   the local mic is muted while the bot speaks, so speakers work, but the
                customer cannot interrupt the bot.
  browser       the call runs through Pipecat's browser connection (WebRTC). The
                browser's echo cancellation removes the bot's voice from the mic, so
                speakers work and barge-in still does. Open the page, allow the mic,
                and press Connect; each connection is one call.

The call ends when the bot records the outcome and says goodbye, or on Ctrl+C.
"""

import argparse
import asyncio
import json

import config
from agent import mock_bank
from voice.pipeline import run_call


def print_outcome(outcome: dict) -> None:
    print("\nOutcome:")
    print(json.dumps(outcome, indent=2, ensure_ascii=False))
    print(f"Transcript: {outcome['transcript_path']}")
    print(
        f"Recording: {config.RUNS_DIR / 'recordings' / (outcome['call_id'] + '.wav')}"
    )


async def bot(runner_args) -> None:
    """--echo browser: Pipecat's development runner calls this once per browser
    connection, with the WebRTC connection the browser opened."""
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    args = runner_args.cli_args
    transport = SmallWebRTCTransport(
        webrtc_connection=runner_args.webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    # The runner owns Ctrl+C; the call must not install its own handler.
    print_outcome(
        await run_call(args.customer, args.version, transport, handle_sigint=False)
    )


async def main(customer_id: str, version: str, echo: str) -> None:
    print_outcome(await run_call(customer_id, version, echo=echo))


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice call with the collections bot.")
    parser.add_argument("--customer", default="C001", choices=list(mock_bank.CUSTOMERS))
    parser.add_argument(
        "--version", default=config.BOT_VERSION, choices=list(config.BOT_VERSIONS)
    )
    parser.add_argument(
        "--echo",
        default="none",
        choices=["none", "half-duplex", "browser"],
        help="how the bot avoids hearing its own voice (see the module docstring)",
    )
    return parser


if __name__ == "__main__":
    args, _ = parser().parse_known_args()
    customer = mock_bank.get_customer(args.customer)
    print(f"Calling {customer['name']} ({args.customer}) with bot {args.version}.")
    if args.version != "v1":
        print(f"Mock OTP for this customer: {customer['otp']}.")
    if args.echo == "browser":
        from pipecat.runner.run import main as run_browser_server

        print("Open http://localhost:7860, allow the microphone and press Connect.\n")
        run_browser_server(parser())  # serves the page; calls bot() per connection
    else:
        print("Speak after the bot's first line. Ctrl+C to hang up.\n")
        asyncio.run(main(args.customer, args.version, args.echo))
