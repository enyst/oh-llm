from __future__ import annotations

import os

DEFAULT_STAGE_A_USER_PROMPT = "Say hello in one word."

DEFAULT_STAGE_B_USER_PROMPT = (
    "Use the terminal tool to run: `echo TOOL_OK`. "
    "Then reply with exactly: TOOL_OK."
)


def stage_a_user_prompt() -> str:
    value = os.environ.get("OH_LLM_STAGE_A_PROMPT", "").strip()
    return value or DEFAULT_STAGE_A_USER_PROMPT


def stage_b_user_prompt() -> str:
    value = os.environ.get("OH_LLM_STAGE_B_PROMPT", "").strip()
    return value or DEFAULT_STAGE_B_USER_PROMPT

