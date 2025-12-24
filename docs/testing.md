# Testing

We use pytest markers to keep CI deterministic while still allowing opt-in integration/e2e validation locally.

## Markers

- `unit`: fast, deterministic tests (runs in CI)
- `integration`: requires local dependencies (e.g. `~/repos/agent-sdk`) and may require secrets
- `e2e`: end-to-end workflows; may require external services and secrets

Unmarked tests are treated as unit-by-default and will run in CI (CI only excludes `integration`/`e2e`).

## Commands

- CI default (unit-by-default; excludes integration/e2e):
  - `uv run pytest -m "not integration and not e2e"`
- Unit-only (explicitly marked `unit`):
  - `uv run pytest -m unit`
- Integration (opt-in, local):
  - `uv run pytest -m integration`
- E2E (opt-in, local):
  - `uv run pytest -m e2e`

## Manual smoke checks (opt-in)

When validating a new model/provider (or a new `agent-sdk` release), use the standalone smoke script:

- `uv run python scripts/openai_sdk_smoke.py --help`

It creates an on-disk SDK profile (no secrets persisted) and runs Stage A, optionally Stage B. To test
against a specific `agent-sdk` worktree, pass `--agent-sdk-path <path>`.

By default, the script uses an isolated temporary `HOME` so it won’t modify your real
`~/.openhands/llm-profiles/` store. Use `--use-user-home` (or `--home-dir <path>`) to opt out.

## Safety

- Never commit or print API keys.
- Prefer referencing secrets via environment variables.
