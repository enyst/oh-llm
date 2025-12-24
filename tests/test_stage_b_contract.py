from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from oh_llm.redaction import REDACTED, redactor_from_env_vars
from oh_llm.stage_b import run_stage_b

pytestmark = pytest.mark.unit


# Stage B probe JSON contract (see `src/oh_llm/sdk_probes/stage_b_probe.py`).
#
# The probe may include additional keys, but these must exist to support:
# - CLI summaries (`run.json` stage B result)
# - autofix capsule context (tool call + observation + final answer)
_STAGE_B_PROBE_REQUIRED_KEYS = {
    "ok",
    "duration_ms",
    "tool_invoked",
    "tool_observed",
    "tool_command_preview",
    "tool_output_preview",
    "final_answer_preview",
}


def _proc(
    *, stdout: str, stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["python"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_fake_agent_sdk(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname = \"agent-sdk\"\n", encoding="utf-8")
    (path / "src" / "openhands").mkdir(parents=True, exist_ok=True)


def test_stage_b_persists_probe_result_and_redacts_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_env = "TEST_SECRET_ENV"
    secret_value = "super-secret-stage-b"
    monkeypatch.setenv(secret_env, secret_value)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    sdk_dir = tmp_path / "agent-sdk"
    _write_fake_agent_sdk(sdk_dir)

    raw = {
        "ok": True,
        "duration_ms": 12,
        "tool_invoked": True,
        "tool_observed": True,
        "tool_command_preview": "echo TOOL_OK",
        "tool_output_preview": f"TOOL_OK {secret_value}",
        "final_answer_preview": "TOOL_OK",
        # Verify redaction works both via secret value replacement and key-name redaction.
        "api_key": secret_value,
        "extra_note": f"debug={secret_value}",
    }
    monkeypatch.setattr(
        "oh_llm.stage_b.uv_run_python",
        lambda **_: _proc(stdout=json.dumps(raw, sort_keys=True)),
    )

    redactor = redactor_from_env_vars(secret_env)
    outcome = run_stage_b(
        agent_sdk_path=sdk_dir,
        artifacts_dir=artifacts_dir,
        model="demo-model",
        base_url="https://example.invalid/v1",
        api_key_env=secret_env,
        timeout_s=1,
        max_iterations=2,
        terminal_type="subprocess",
        redactor=redactor,
    )

    assert outcome.ok is True
    assert outcome.tool_invoked is True
    assert outcome.tool_observed is True

    config_text = (artifacts_dir / "stage_b_config.json").read_text(encoding="utf-8")
    assert secret_value not in config_text

    probe_text = (artifacts_dir / "stage_b_probe_result.json").read_text(encoding="utf-8")
    assert secret_value not in probe_text
    assert REDACTED in probe_text

    probe_payload = _read_json(artifacts_dir / "stage_b_probe_result.json")
    assert _STAGE_B_PROBE_REQUIRED_KEYS.issubset(probe_payload.keys())
    assert probe_payload.get("api_key") == REDACTED


def test_stage_b_treats_nonzero_exit_as_failure_when_probe_claims_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    sdk_dir = tmp_path / "agent-sdk"
    _write_fake_agent_sdk(sdk_dir)

    raw = {
        "ok": True,
        "duration_ms": 12,
        "tool_invoked": True,
        "tool_observed": True,
        "tool_command_preview": "echo TOOL_OK",
        "tool_output_preview": "TOOL_OK",
        "final_answer_preview": "TOOL_OK",
    }
    monkeypatch.setattr(
        "oh_llm.stage_b.uv_run_python",
        lambda **_: _proc(stdout=json.dumps(raw), returncode=2),
    )

    outcome = run_stage_b(
        agent_sdk_path=sdk_dir,
        artifacts_dir=artifacts_dir,
        model="demo-model",
        base_url=None,
        api_key_env="TEST_API_KEY",
        timeout_s=1,
        max_iterations=2,
        terminal_type="subprocess",
        redactor=redactor_from_env_vars(),
    )

    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.get("type") == "ProbeError"


def test_stage_b_handles_non_json_probe_stdout_and_redacts_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_env = "TEST_SECRET_ENV"
    secret_value = "secret-in-probe-stdout"
    monkeypatch.setenv(secret_env, secret_value)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    sdk_dir = tmp_path / "agent-sdk"
    _write_fake_agent_sdk(sdk_dir)

    stdout = f"not json: {secret_value}\n"
    monkeypatch.setattr(
        "oh_llm.stage_b.uv_run_python",
        lambda **_: _proc(stdout=stdout, returncode=0),
    )

    redactor = redactor_from_env_vars(secret_env)
    outcome = run_stage_b(
        agent_sdk_path=sdk_dir,
        artifacts_dir=artifacts_dir,
        model="demo-model",
        base_url=None,
        api_key_env="TEST_API_KEY",
        timeout_s=1,
        max_iterations=2,
        terminal_type="subprocess",
        redactor=redactor,
    )

    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.get("type") == "ProbeError"

    probe_text = (artifacts_dir / "stage_b_probe_result.json").read_text(encoding="utf-8")
    assert secret_value not in probe_text
    assert REDACTED in probe_text
