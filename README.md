# oh-llm

Local CLI/TUI (v1 is CLI-first) to validate whether a newly released LLM works with the
OpenHands **Software Agent SDK** (`~/repos/agent-sdk` by default).

Given a model config (model name + optional base URL + API key via env var), `oh-llm` runs:

- **Stage A**: basic connectivity + completion
- **Stage B**: end-to-end agent run with tool calling (terminal tool)

If a run fails, the longer-term goal is to let an OpenHands agent debug and open an upstream PR
against `OpenHands/software-agent-sdk`.

## Quickstart

Prereqs:
- Python `>= 3.12`
- `uv`
- Local agent-sdk checkout at `~/repos/agent-sdk` (or set `OH_LLM_AGENT_SDK_PATH`)

Setup:

```bash
uv sync --dev
uv run oh-llm --help
```

Create a profile (no secrets stored on disk):

```bash
export MY_LLM_API_KEY="YOUR_API_KEY_VALUE"  # value is never stored by oh-llm
uv run oh-llm profile add demo \
  --model "gpt-5-mini" \
  --api-key-env MY_LLM_API_KEY
```

Notes:
- `--base-url` is optional; use it for proxies/self-hosted providers, otherwise omit it.
- The profile stores only the **env var name** (`MY_LLM_API_KEY`), not the value.

Run Stage A (smoke):

```bash
uv run oh-llm run --profile demo
```

Run Stage A + Stage B (recommended):

```bash
uv run oh-llm run --profile demo --stage-b
```

If you emit machine-readable output, redact any env vars that might appear in logs/errors:

```bash
uv run oh-llm run --profile demo --stage-b --json --redact-env MY_LLM_API_KEY
```

## Where data lives

- Runs: `~/.oh-llm/runs` (override with `OH_LLM_RUNS_DIR` or `oh-llm run --runs-dir ...`)
- Profiles (SDK, no secrets): `~/.openhands/llm-profiles/<profile_id>.json` (written by `oh-llm profile add`)
- Profile metadata (env var name only): `~/.oh-llm/profiles/<profile_id>.json` (written by `oh-llm profile add`)

## Safety

- API keys are never written to git or stored directly on disk; only the **env var name** is saved.
- If you use a local `.env` file for convenience, keep it out of git (this repo’s `.gitignore` includes `.env`).

## Docs

- `docs/profiles.md` (profile storage + CLI)
- `docs/runs.md` (runs + artifacts)
- `docs/testing.md` (pytest markers)
- `docs/manual-qa-tmux.md` (manual QA workflow)
- `docs/agent-sdk-execution.md` (how `oh-llm` runs agent-sdk)
- `docs/providers/README.md` (provider quickrefs + quirks)
- `prd.md` (product/design notes)
