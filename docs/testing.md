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

## Safety

- Never commit or print API keys.
- Prefer referencing secrets via environment variables.
