"""Export a finished call: its audio and its transcript, in one folder.

    runs/exports/<call_id>/
        recording.wav     both sides of the call, stereo: customer left, bot right
                          (voice calls only; text calls have no audio)
        transcript.txt    the call as people read it: who said what, when, and the outcome
        transcript.json   the full transcript log: turns, tool calls, guardrail actions

The customer's lines are what speech-to-text heard, which is also what the bot
answered. The demo console exports every call when it ends.
"""

import json
import shutil
from pathlib import Path

import config

EXPORTS_DIR = config.RUNS_DIR / "exports"
FILES = ("recording.wav", "transcript.txt", "transcript.json")


def clock(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, seconds), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def transcript_text(transcript: dict) -> str:
    """The call as plain text: a header, the turns with their times, and the outcome."""
    outcome = transcript.get("outcome") or {}
    lines = [
        f"Call {transcript['call_id']}",
        (
            f"Customer {transcript['customer_id']}, bot {transcript['bot_version']}, "
            f"started {transcript['started_at']}"
        ),
        "",
    ]
    names = {"bot": "Bot", "customer": "Customer"}
    for event in transcript["events"]:
        if event["type"] in names:
            lines.append(
                f"[{clock(event['at_seconds'])}] {names[event['type']]}: {event['text']}"
            )
        elif event["type"] == "ignored_noise":
            lines.append(
                f"[{clock(event['at_seconds'])}] (noise ignored: {event['text']})"
            )
    lines += ["", "Outcome:", json.dumps(outcome, indent=2, ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def export_call(call_id: str) -> list[str]:
    """Write the call's export folder. Returns the names of the files written."""
    transcript_path = config.RUNS_DIR / "transcripts" / f"{call_id}.json"
    recording_path = config.RUNS_DIR / "recordings" / f"{call_id}.wav"
    folder = EXPORTS_DIR / call_id
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    if recording_path.exists():
        shutil.copyfile(recording_path, folder / "recording.wav")
        written.append("recording.wav")
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    (folder / "transcript.txt").write_text(
        transcript_text(transcript), encoding="utf-8"
    )
    shutil.copyfile(transcript_path, folder / "transcript.json")
    written += ["transcript.txt", "transcript.json"]
    return written


def export_file(call_id: str, name: str) -> Path | None:
    """One exported file, or None. Only the known names, so no other path is served."""
    path = EXPORTS_DIR / call_id / name
    return path if name in FILES and path.is_file() else None
