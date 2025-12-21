from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_llm.agent_sdk import resolve_agent_sdk_path, uv_available, uv_run_python
from oh_llm.profiles import upsert_profile

pytestmark = pytest.mark.integration


def test_openhands_llm_registry_can_load_oh_llm_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not uv_available():
        pytest.skip("uv not available")

    agent_sdk_path = resolve_agent_sdk_path()
    if not agent_sdk_path.exists():
        pytest.skip(f"agent-sdk not found at {agent_sdk_path}")

    monkeypatch.setenv("HOME", str(tmp_path))

    upsert_profile(
        profile_id="demo",
        model="gpt-5-mini",
        base_url="https://example.invalid",
        api_key_env="DEMO_API_KEY",
        overwrite=True,
    )

    proc = uv_run_python(
        agent_sdk_path=agent_sdk_path,
        python_args=[
            "-c",
            (
                "import json; "
                "from openhands.sdk.llm.llm_registry import LLMRegistry; "
                "reg = LLMRegistry(); "
                "llm = reg.load_profile('demo'); "
                "print(json.dumps({'model': llm.model, 'base_url': llm.base_url}))"
            ),
        ],
        env={"HOME": str(tmp_path)},
    )
    if proc.returncode != 0:
        raise AssertionError((proc.stdout or "") + (proc.stderr or ""))

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["model"] == "gpt-5-mini"
    assert payload["base_url"] == "https://example.invalid"
