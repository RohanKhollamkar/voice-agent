"""The v2 reply check as a pipeline step, just before speech.

The agent core already runs the same check (agent/guardrails.py) on every reply, so
normally this step passes text through unchanged. It is the last gate before audio:
anything that reaches it unchecked is checked here, and a block is logged in the
call's transcript. The closing line, built in code from the recorded outcome, is
not checked, as in text mode.
"""

from loguru import logger
from pipecat.frames.frames import Frame, LLMTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

import config
from agent.core import Agent
from agent.guardrails import check_reply


class ReplyCheckStep(FrameProcessor):
    def __init__(self, agent: Agent):
        super().__init__()
        self.agent = agent

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        guarded = self.agent.state.guarded and not self.agent.ended
        if guarded and isinstance(frame, LLMTextFrame) and frame.text.strip():
            verified = self.agent.state.otp_verified or not config.ENFORCE_OTP
            text, blocks = check_reply(
                frame.text,
                self.agent.allowed_numbers,
                verified,
                tool_names=self.agent.state.v2_1,
            )
            for block in blocks:
                logger.warning(f"Reply check blocked: {block}")
                self.agent._log(type="guardrail_block", step="voice", **block)
            if blocks:
                frame = LLMTextFrame(text=text + " ")
        await self.push_frame(frame, direction)
