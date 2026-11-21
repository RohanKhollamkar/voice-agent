"""Demo console: one page to run and watch live calls.

    python -m voice.demo            # then open http://localhost:7860/demo
    python -m voice.demo --open     # opens the browser once the server is up

The page (voice/demo.html) starts and ends calls and displays what happens. Every
pane is fed from the events the agent core writes to the call's transcript, streamed
to the page as server-sent events; nothing here changes how the bot behaves.

When a call ends, its recording (voice mode) and transcript are exported to
runs/exports/<call_id>/ (see voice/export.py), and the page offers them for download.

Voice mode uses the browser connection (Pipecat's SmallWebRTC, as in
`python -m voice.call --echo browser`), so the browser's echo cancellation applies
and barge-in works. Text mode takes typed customer turns and uses no speech credits.

The server listens on localhost only.
"""

import argparse
import asyncio
import json
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

import config
from agent import mock_bank
from agent.core import Agent
from voice.export import export_call, export_file

HOST, PORT = "127.0.0.1", 7860
PAGE = Path(__file__).with_name("demo.html")


@dataclass
class Call:
    agent: Agent
    mode: str  # "voice" or "text"
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    over: bool = False
    task: asyncio.Task | None = None  # voice: the running pipeline
    connection: object = None  # voice: the browser connection
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # text: one turn at a time

    def publish(self, event: dict) -> None:
        # The call's clock as the agent measures it (text mode counts words spoken),
        # added for the page's timer. Not stored in the transcript.
        message = {**event, "call_clock": round(self.agent.elapsed_seconds(), 1)}
        for queue in self.subscribers:
            queue.put_nowait(message)


calls: dict[str, Call] = {}
app = FastAPI(title="Mumbai Bank demo console")


class StartRequest(BaseModel):
    customer_id: str
    version: str = config.BOT_VERSION
    mode: str = "text"


class SayRequest(BaseModel):
    text: str


def get_call(call_id: str) -> Call:
    if call_id not in calls:
        raise HTTPException(404, "No such call")
    return calls[call_id]


def close(call: Call) -> None:
    """The call has ended and its outcome is settled: export it, then close the stream."""
    call.over = True
    try:
        files = export_call(call.agent.state.call_id)
        call.publish({"type": "export", "files": files})
    except OSError as error:  # an export problem must not keep the call open
        call.publish({"type": "export", "files": [], "error": str(error)})
    call.publish({"type": "call_over"})


async def finish(call: Call) -> None:
    """Text mode: settle the outcome (the agent posts it and logs it), then close."""
    if call.over:
        return
    call.over = True
    await call.agent.finish()
    close(call)


@app.get("/demo", response_class=HTMLResponse)
async def page() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/customers")
async def customers() -> list[dict]:
    return [{"id": cid, "name": c["name"]} for cid, c in mock_bank.CUSTOMERS.items()]


@app.post("/api/calls")
async def start_call(request: StartRequest) -> dict:
    mock_bank.get_customer(request.customer_id)  # unknown ids fail here
    if request.version not in config.BOT_VERSIONS or request.mode not in (
        "voice",
        "text",
    ):
        raise HTTPException(
            400, f"version is one of {config.BOT_VERSIONS}; mode is voice or text"
        )
    # Voice runs on real time; text mode, like the evals, estimates time from words.
    clock = "wall" if request.mode == "voice" else "spoken"
    agent = Agent(request.customer_id, request.version, clock=clock)
    call = Call(agent=agent, mode=request.mode)
    agent.listeners.append(call.publish)
    calls[agent.state.call_id] = call
    return {"call_id": agent.state.call_id, "bot_name": config.BOT_NAME}


@app.get("/api/calls/{call_id}/events")
async def events(call_id: str) -> StreamingResponse:
    """Server-sent events: everything logged so far, then each new event."""
    call = get_call(call_id)
    queue: asyncio.Queue = asyncio.Queue()
    for event in call.agent.events:
        queue.put_nowait(
            {**event, "call_clock": round(call.agent.elapsed_seconds(), 1)}
        )
    if call.over:
        queue.put_nowait({"type": "call_over"})
    call.subscribers.append(queue)

    async def stream():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] == "call_over":
                    return
        finally:
            call.subscribers.remove(queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/calls/{call_id}/open")
async def open_text_call(call_id: str) -> dict:
    """Text mode: the bot's opening line."""
    call = get_call(call_id)
    async with call.lock:
        if not call.agent.events:
            await call.agent.start()
    return {"ok": True}


@app.post("/api/calls/{call_id}/say")
async def say(call_id: str, request: SayRequest) -> dict:
    """Text mode: one customer turn. The bot's reply arrives on the event stream."""
    call = get_call(call_id)
    if call.mode != "text" or call.over:
        raise HTTPException(409, "Not an open text call")
    async with call.lock:
        await call.agent.respond(request.text.strip())
        if call.agent.ended:
            await finish(call)
    return {"ok": True}


@app.get("/api/calls/{call_id}/files/{name}")
async def download(call_id: str, name: str) -> FileResponse:
    """An exported file of an ended call, as a download."""
    get_call(call_id)  # only calls this server ran
    path = export_file(call_id, name)
    if path is None:
        raise HTTPException(404, "No such file for this call")
    return FileResponse(path, filename=f"call_{call_id[:8]}_{name}")


@app.post("/api/calls/{call_id}/end")
async def end_call(call_id: str) -> dict:
    """The customer hangs up. Voice: close the connection, and the pipeline settles
    the outcome as it stops. Text: settle it here."""
    call = get_call(call_id)
    if call.mode == "voice" and call.task:
        if call.connection is not None:
            await call.connection.disconnect()
        try:
            await asyncio.wait_for(asyncio.shield(call.task), timeout=30)
        except TimeoutError:
            call.task.cancel()
    else:
        async with call.lock:
            await finish(call)
    return {"ok": True}


def add_voice_routes() -> None:
    """The browser connection, as `voice.call --echo browser` uses it."""
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
    from pipecat.transports.smallwebrtc.request_handler import (
        SmallWebRTCPatchRequest,
        SmallWebRTCRequest,
        SmallWebRTCRequestHandler,
    )
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from voice.pipeline import run_call

    handler = SmallWebRTCRequestHandler(host=HOST)

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest) -> dict | None:
        call_id = (request.request_data or {}).get("call_id", "")
        call = get_call(call_id)

        async def on_connection(connection: SmallWebRTCConnection) -> None:
            transport = SmallWebRTCTransport(
                webrtc_connection=connection,
                params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
            )
            call.connection = connection
            state = call.agent.state

            def on_event(event: dict) -> None:
                # The bot ended the call: hang up the browser connection too, so the
                # page does not stay "connected" while the pipeline winds down.
                if event["type"] == "call_ended":
                    asyncio.get_running_loop().create_task(connection.disconnect())

            call.agent.listeners.append(on_event)

            async def run() -> None:
                try:  # run_call settles the outcome itself, however the call ends
                    await run_call(
                        state.customer_id,
                        state.bot_version,
                        transport,
                        handle_sigint=False,
                        agent=call.agent,
                    )
                finally:
                    close(call)  # the recording is written by now (see run_call)

            call.task = asyncio.create_task(run())

        return await handler.handle_web_request(request, on_connection)

    @app.patch("/api/offer")
    async def ice_candidate(request: SmallWebRTCPatchRequest) -> dict:
        await handler.handle_patch_request(request)
        return {"status": "success"}


def open_when_ready(url: str) -> None:
    """Open the page in the default browser once the server accepts connections."""
    for _ in range(100):
        try:
            socket.create_connection((HOST, PORT), timeout=1).close()
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo console for live calls.")
    parser.add_argument(
        "--open", action="store_true", help="open the page in a browser"
    )
    args = parser.parse_args()
    add_voice_routes()
    url = f"http://localhost:{PORT}/demo"
    print(f"Demo console: {url}")
    if args.open:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
