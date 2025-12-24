# Agent-SDK execution (v1 decision)

`oh-llm` is a local tool that validates whether a new LLM works with the OpenHands **Software Agent SDK**.

To run the SDK reliably, `oh-llm` treats the SDK checkout (`~/repos/agent-sdk` by default) as an **external uv workspace** and executes SDK code in a subprocess:

- `uv --directory $OH_LLM_AGENT_SDK_PATH run python ...`

## Rationale

- Keeps `oh-llm`’s own dependencies small and CI deterministic (unit tests don’t need SDK deps).
- Ensures we test the SDK the way it’s meant to run (uv workspace imports and pinned deps).
- Aligns with the auto-fix workflow (SDK worktrees can be created and validated using `uv run` inside the worktree).

## Configuration

- SDK path: `OH_LLM_AGENT_SDK_PATH` (defaults to `~/repos/agent-sdk`)
- CLI overrides: `oh-llm run --agent-sdk-path <path>` (alias: `--sdk-path`) and similar flags on `oh-llm autofix ...`
- `uv` must be on `PATH`.

## CLI helpers

- `oh-llm sdk info` prints the configured SDK path + git SHA (when available).
- `oh-llm sdk check-import` attempts an `import openhands.sdk` using the SDK’s uv environment.
