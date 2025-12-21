# Runs + artifacts

Each `oh-llm run` creates a per-run directory containing:

- `run.json` (stable schema; no secrets)
- `logs/run.log`
- `artifacts/` (reserved for repro harnesses, patches, transcripts)

## Location

Default: `~/.oh-llm/runs`

Override:
- Env: `OH_LLM_RUNS_DIR`
- CLI: `oh-llm run --runs-dir ...`

## `run.json` schema (v1)

Top-level keys:
- `schema_version` (int, currently `1`)
- `run_id` (string)
- `created_at` (UTC ISO-8601)
- `profile` (object; redacted; never contains raw secrets)
- `agent_sdk` (object: `path`, `git_sha`, `git_dirty`)
- `host` (object: basic host/python info)
- `stages` (object: stage key → `{name,status,duration_ms,...}`; statuses start as `not_run`)

Stage-specific keys:
- `result` (object, optional): stage output summary (redacted)
- `error` (object, optional): `{classification,type,message,hint}` (redacted)
