# Troubleshooting

This doc is intentionally pragmatic: what failed, where to look, and what to do next.

## Where to look first

- Run JSON: `~/.oh-llm/runs/<run>/run.json`
- Run log: `~/.oh-llm/runs/<run>/logs/run.log`
- Stage artifacts: `~/.oh-llm/runs/<run>/artifacts/`

Useful commands:

- `uv run oh-llm runs list`
- `uv run oh-llm runs show <run> --json`

## Failure classifications → next action

- `credential_or_config`
  - Fix configuration (profile, env vars, base URL, model id).
  - Do **not** run autofix unless you are certain it’s an SDK bug and you pass `--force`.
- `sdk_or_provider_bug`
  - If it’s reproducible with a minimal prompt, consider `oh-llm autofix ...` to have an agent attempt a fix and open an upstream PR.
- `unknown`
  - Treat as `sdk_or_provider_bug` until you can isolate whether it’s config.

## Common failures

### “Missing required option: --profile”

- Cause: you ran `oh-llm run` without `--profile`.
- Fix: `uv run oh-llm profile add <name> ...` then rerun with `--profile <name>`.

### “Profile not found”

- Cause: profile id/name doesn’t exist in the local store.
- Fix: `uv run oh-llm profile list` to see available profiles.

### “API key env var not set”

- Cause: profile points at an env var name, but that env var isn’t set in the process environment.
- Fix:
  - `export <ENV_VAR_NAME>=...`
  - or set it via your `.env`/shell tooling (but keep `.env` out of git).

### 401/403 (auth) vs 404 (wrong base URL/model) vs 429 (quota)

- 401/403: credentials invalid, missing, or insufficient scope.
- 404/400: wrong base URL, wrong model id, wrong “deployment name” (common for Azure-style providers).
- 429: quota/rate limit; retry later or reduce load.

Look in:
- `run.json` failure classification + error message
- `logs/run.log` for raw error previews (redacted if configured)

### Stage A passes, Stage B fails

Stage B is the tool-calling end-to-end agent run.

Common causes:
- Provider/model supports basic chat but tool calling is broken or different.
- Wrong model id: some providers expose separate “tool-capable” models.
- Provider requires extra headers/options (should be handled via SDK/LiteLLM, but quirks exist).

Look in:
- `artifacts/stage_b_probe_result.json` (includes previews of tool command/output and final answer)

Next steps:
- Try a known-good model on the same provider to isolate provider-vs-model.
- If it looks like an SDK parsing/compat bug, run `oh-llm autofix` on the failing run.

### Stage B probe “did not return JSON”

- Cause: the probe crashed or logged non-JSON output.
- Look in:
  - `artifacts/stage_b_probe_result.json` (captures stdout/stderr/returncode)
  - `logs/run.log`
- Next steps:
  - Ensure `uv` is installed.
  - Ensure `OH_LLM_AGENT_SDK_PATH` points to a valid agent-sdk checkout.

## When to run autofix

Recommended: only when you’ve ruled out credential/config errors.

- If classification is `credential_or_config`, fix config first (or pass `--force` if you know it’s not config).
- If classification is `sdk_or_provider_bug`, autofix is appropriate.

