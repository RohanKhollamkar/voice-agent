"""The reply check before speech lives in agent/guardrails.py and runs inside the agent
core, so text mode and voice mode share it. Stage 5 adds a pipeline step here only if
the voice pipeline needs one."""
