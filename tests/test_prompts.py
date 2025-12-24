from __future__ import annotations

import pytest

from oh_llm.prompts import (
    DEFAULT_STAGE_A_USER_PROMPT,
    DEFAULT_STAGE_B_USER_PROMPT,
    stage_a_user_prompt,
    stage_b_user_prompt,
)

pytestmark = pytest.mark.unit


def test_prompts_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OH_LLM_STAGE_A_PROMPT", raising=False)
    monkeypatch.delenv("OH_LLM_STAGE_B_PROMPT", raising=False)
    assert stage_a_user_prompt() == DEFAULT_STAGE_A_USER_PROMPT
    assert stage_b_user_prompt() == DEFAULT_STAGE_B_USER_PROMPT


def test_prompts_use_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OH_LLM_STAGE_A_PROMPT", " hello ")
    monkeypatch.setenv("OH_LLM_STAGE_B_PROMPT", " do the thing ")
    assert stage_a_user_prompt() == "hello"
    assert stage_b_user_prompt() == "do the thing"


def test_prompts_ignore_empty_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OH_LLM_STAGE_A_PROMPT", "   ")
    monkeypatch.setenv("OH_LLM_STAGE_B_PROMPT", "")
    assert stage_a_user_prompt() == DEFAULT_STAGE_A_USER_PROMPT
    assert stage_b_user_prompt() == DEFAULT_STAGE_B_USER_PROMPT


def test_probes_use_prompt_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OH_LLM_STAGE_A_PROMPT", "A_PROMPT")
    monkeypatch.setenv("OH_LLM_STAGE_B_PROMPT", "B_PROMPT")

    from oh_llm.sdk_probes import stage_a_probe, stage_b_probe

    assert stage_a_probe._prompt() == "A_PROMPT"
    assert stage_b_probe._prompt() == "B_PROMPT"

