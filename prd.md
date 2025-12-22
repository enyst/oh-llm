# oh-llm — Product Requirements Document (PRD)

## Summary

`oh-llm` is a local-first tool (CLI first; TUI planned) for validating whether a newly released LLM works with the OpenHands Software Agent SDK (`~/repos/agent-sdk`). When a model fails compatibility tests, `oh-llm` launches an OpenHands agent to reproduce, diagnose, patch the SDK, and open an upstream PR against `OpenHands/software-agent-sdk`.

This repo is the “LLM onboarding & compatibility gate” for OpenHands.

## Problem

New or newly supported LLMs often break in subtle ways when used through the SDK (litellm routing, tool calling formats, streaming, responses vs chat endpoints, auth headers, base URLs, etc.). Today, finding out is ad-hoc and expensive:

- It’s unclear what “works” means (what minimum behaviors are required).
- Repro steps and logs aren’t consistently captured.
- Fixing the SDK for a model requires context + manual effort.

## Goals

- Provide a simple UX to enter LLM connection details (model id + base URL + API key + provider-specific bits).
- Run a deterministic compatibility suite against `~/repos/agent-sdk`.
- Present clear results: pass/fail with actionable error details and logs.
- On failure, automatically run an OpenHands agent that:
  - reproduces the failure,
  - identifies the SDK gap,
  - implements a fix in the SDK,
  - runs SDK tests / minimal checks,
  - opens an upstream PR with a concise explanation.

## Non-goals (initially)

- Becoming a general LLM benchmarking framework (quality/safety benchmarks, leaderboards).
- Managing long-lived production secrets for many orgs.
- Running large-scale distributed test fleets.

## Primary users / personas

- **You (initial)**: adds a new model, runs the suite, inspects failures, triggers auto-fix PRs.
- **Later contributors**: other OpenHands devs/operators who need a repeatable “does this model work?” gate.

## UX

### Entry points

1) **CLI** (v1, required):
- Scriptable commands to create/update profiles, run the suite, and export artifacts.

2) **TUI** (planned, vNext):
- Local UI to create/edit profiles, run tests, and browse artifacts.
- Likely a subcommand (e.g. `oh-llm tui`).

### Core flow: add model → test → (maybe) auto-fix

1) Create a profile (non-secret config stored; secrets referenced by env var name only):
   - `oh-llm profile add <id> --model <litellm-model> [--base-url <url>] --api-key-env <ENV_VAR_NAME>`
2) Export the API key for the chosen env var in your shell.
3) Run the compatibility suite:
   - v1 smoke: `oh-llm run --profile <id>` (Stage A)
   - full compatibility: `oh-llm run --profile <id> --stage-b` (Stage A + Stage B)
4) Inspect results:
   - terminal output + `run.json`, logs, and artifacts under the run directory
5) If failing and it looks like an SDK incompatibility:
   - launch an auto-fix agent run (v1 planned) that reproduces, patches `~/repos/agent-sdk`, and opens an upstream PR

In vNext, the TUI provides the same flow via forms/buttons, plus run browsing.

### Output expectations

For each run, keep:
- profile used (without secrets)
- run metadata (time, git SHA of agent-sdk, host info)
- stage results (pass/fail/duration)
- logs + stack traces
- artifacts (repro script, patches, agent transcript)

## Compatibility suite (v1)

The suite should be fast (target: < 2–5 minutes) and structured as progressive gates.

### Stage A — Connectivity + basic completion

Purpose: verify credentials and base URL wiring.

- Create `openhands.sdk.LLM` with the provided config.
- Run a direct completion (`llm.completion(...)`) with a minimal prompt:
  - “Say hello in one word.”
- Assert:
  - a response is returned,
  - content is parseable into expected SDK message structures,
  - errors are mapped sensibly (no cryptic provider exceptions).

### Stage B — End-to-end agent run (tool calling) (recommended)

Purpose: end-to-end SDK run with tool calling (full compatibility check).

- Create `Agent(llm=..., tools=[TerminalTool])`.
- Run a short prompt that forces a deterministic tool call, e.g.:
  - “Run `echo TOOL_OK` in the terminal and then reply with TOOL_OK.”
- Assert:
  - `Conversation` completes,
  - tool call was invoked (native or non-native conversion),
  - tool output is observed by the agent,
  - agent reports a final “TOOL_OK” in natural language.

Note: tool calling is required for “fully works with the agent-sdk”. The SDK includes a non-native tool calling compatibility layer (prompt-based conversion), so models that don’t support tool calling natively can still pass Stage B as long as the SDK can reliably translate tool intents into tool invocations.

### Stage C — Optional advanced gates (toggleable)

- streaming on/off
- image input (if model claims vision)
- responses API vs chat completions (as appropriate)
- persistence/resume using `Conversation(..., persistence_dir=...)`

## Auto-fix workflow (OpenHands agent)

### Trigger conditions

- Any stage fails and the error appears SDK-level (not clearly “bad creds”).
- User explicitly requests “auto-fix”.

### Inputs to the auto-fix agent

- The profile config (redacted) + a way to retrieve secrets at runtime.
- The failing run’s logs + stack trace.
- The minimal reproduction harness `oh-llm` used.
- The exact SDK revision:
  - `~/repos/agent-sdk` git SHA
  - whether it’s clean/dirty

### Workspace model

To avoid contaminating your main SDK checkout:
- Create a git worktree for `~/repos/agent-sdk` for each auto-fix run.
- Run the agent in that worktree.
- Capture diffs and test outputs.

### Expected agent outputs

- A short diagnosis: what broke and why.
- A code change in SDK that fixes the issue for the new model without regressions.
- Validation:
  - minimal local reproduction passes,
  - targeted SDK tests (or a documented reason they can’t run).
- An upstream PR:
  - branch name includes the model id (or a safe slug)
  - PR body includes repro steps + logs excerpt + rationale.

### Upstream PR mechanics

`oh-llm` should support:
- opening PRs via `gh` (GitHub CLI) using the user’s auth
- pushing either to:
  - a fork (preferred), or
  - a branch on upstream if the user has permission

If PR creation fails:
- leave a local branch with commits
- output instructions to open the PR manually

## System design (v1)

### Components

**v1**
- **CLI**: entry point for running suites and automation.
- **Runner**: executes compatibility suite stages; collects artifacts.
- **Agent launcher**: runs OpenHands agent for auto-fix in an SDK worktree.

**vNext**
- **TUI app**: local UI for profiles and runs.

### Data model (high-level)

- `llm_profile`
  - id/name (stable)
  - provider/model/base_url
  - auth reference (where secrets are stored)
  - optional overrides (timeouts, streaming, etc.)
- `run`
  - profile_id
  - sdk_sha + environment snapshot
  - stage results + logs + artifacts
- `autofix_run` (subset of run)
  - worktree path + branch
  - PR URL (if created)

### Secrets handling

We must avoid leaking API keys into:
- git
- logs
- PR bodies

Preferred approach:
- **v1**: do not store provider secrets at rest. Store only the *name* of the environment variable to read at runtime.
- Always redact secrets from persisted run artifacts.

SDK note: `LLMRegistry.save_profile(..., include_secrets=False)` exists and is a good building block. `oh-llm` should reuse SDK profiles on disk (`~/.openhands/llm-profiles/*.json`) for the non-secret portion of LLM config and inject secrets at runtime.

### Multi-user (deferred)

We are explicitly **not** solving multi-user auth/hosting in v1. Future deployment options include:
- OpenHands Cloud delegated runs (bearer auth), if we can solve provider-key handling.
- GitHub Actions runner, likely requiring an LLM proxy/shared secrets or self-hosted runners for custom base URLs.

## Observability

- Store structured run results in a local directory (per-run folder).
- Keep raw logs + a summarized “error capsule” for prompt injection into the auto-fix agent.
- Optionally send a summary to Agent Mail with `thread_id` = `pr-<number>` or a local run id.

## Risks / constraints

- **Model providers differ**: “model works” can vary by tool calling and streaming support.
- **Non-determinism**: tests must be robust to variance (keep prompts tight).
- **Secrets**: never leak API keys to git or PRs.
- **Cost**: repeated runs can be expensive; track approximate cost per run.

## Milestones (suggested)

1) Local runner (CLI): define profile format, run Stage A, save artifacts.
2) Extend suite: implement Stage B + optional advanced gates.
3) Auto-fix agent workflow: worktree + OpenHands run + local patch output.
4) Upstream PR automation: gh integration, fork/branch management.
5) TUI: profile/run management + artifact viewer.
6) Polish: better failure classification UX.
7) (Optional later) Web server: auth + basic HTML form + run endpoint.

## Decisions (current)

- **Profiles**: reuse SDK `LLMRegistry` profiles on disk for the non-secret config; inject secrets at runtime.
- **Provider scope**: anything supported by litellm; from `oh-llm`’s POV this is “OpenAI-compatible style config” (model + optional base_url + credentials / provider fields).
- **Definition of “works”**:
  - **v1 “smoke”**: Stage A must pass (credentials/base_url/SDK wiring).
  - **full compatibility**: Stage A + Stage B should pass; tool calling is required (native or via the SDK’s non-native tool calling compatibility layer).
- **Auto-fix boundaries**: the agent may change whatever is needed for good support (SDK code, tests, docs/examples).
- **Upstream PR target**: upstream is `OpenHands/software-agent-sdk`, PRs target `main`.
- **Failure classification**: detect “credential/config error” vs “likely SDK bug”; only offer auto-fix by default for the latter (still allow a force option).
- **Implementation (v1)**: Python (matches SDK; easiest to run the suite and integrate agent workflows).
- **Execution (v1)**: local-only, CLI first. No multi-user hosting in v1.
- **SDK under test (v1)**: use `~/repos/agent-sdk` (configurable later if needed).
- **Auth fields (v1)**: only `model`, optional `base_url`, and a single `api_key` read from a user-provided environment variable name.

## Open questions

- **Suite scope**: do we ship Stage A only first (smoke), or block “works” on Stage B from day one?
- **Stage prompts**: which minimal prompts are stable across models (and cheap), especially for Stage B deterministic tool runs?
- **Failure classification**: which heuristics are enough to confidently label “bad creds / bad base_url / quota” vs “SDK bug” before offering auto-fix?
- **TUI tech**: what library (e.g. `textual`, `urwid`, `prompt_toolkit`, custom curses) best fits a fast local UI with run browsing?
- **Auto-fix prompts**: what is the minimal “prompt pack” to consistently reproduce + patch SDK issues (and avoid overfitting)?
- **GitHub Actions runner**: do we support this soon, and if so, which constraints apply (self-hosted runners for custom base URLs, secrets handling, cost controls)?
