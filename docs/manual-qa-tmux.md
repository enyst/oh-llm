# Manual QA (tmux workflow)

This doc is a lightweight, repeatable manual QA workflow for reviewing `oh-llm` changes locally.

It complements unit tests by making it easy to:
- run a small set of CLI commands
- watch run artifacts/logs in real time
- (later) launch the TUI

## Setup

Prereqs:
- `tmux`
- `uv` + this repo set up (`uv sync --dev`)

## Start a tmux session (CLI + logs)

From the repo root:

```bash
# Optional: override before starting tmux (panes inherit this):
# export OH_LLM_RUNS_DIR=/tmp/oh-llm-runs

export OH_LLM_RUNS_DIR="${OH_LLM_RUNS_DIR:-$HOME/.oh-llm/runs}"
RUNS_DIR="$OH_LLM_RUNS_DIR"
SESSION="oh_llm_qa"

tmux new-session -d -s "$SESSION" -n cli "uv run oh-llm --help; exec $SHELL"
tmux split-window -h -t "$SESSION:0" "ls -1td \"$RUNS_DIR\"/*/ 2>/dev/null | head; exec $SHELL"
tmux split-window -v -t "$SESSION:0.1" "LATEST=\"$(ls -1td \"$RUNS_DIR\"/*/ 2>/dev/null | head -n1)\"; [ -n \"$LATEST\" ] && tail -F \"$LATEST/logs/run.log\" 2>/dev/null || true; exec $SHELL"

tmux select-layout -t "$SESSION:0" tiled
tmux attach -t "$SESSION"
```

Notes:
- The log tail pane will be empty until at least one run directory exists.
- If you override runs dir, `export OH_LLM_RUNS_DIR=...` *before* starting tmux.

## Reviewer checklist (v1)

Run these commands in the CLI pane:

- `uv run oh-llm --help`
- `uv run oh-llm sdk info --json`
- `uv run oh-llm sdk check-import --json` (requires local `agent-sdk` checkout)
- `uv run oh-llm run --profile demo --json`

Expected:
- CLI commands exit successfully where applicable.
- `oh-llm run ...` creates a new run directory with:
  - `run.json`
  - `logs/run.log`
  - `artifacts/`
- `run.json` contains `schema_version`, SDK SHA (if available), and stage placeholders.

## Cleanup

```bash
tmux kill-session -t "oh_llm_qa"
```
