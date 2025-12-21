# oh-llm — Product Requirements Document (PRD)

## Summary

`oh-llm` is a local-first tool (TUI + small web server) for validating whether a newly released LLM works with the OpenHands Software Agent SDK (`~/repos/agent-sdk`). When a model fails compatibility tests, `oh-llm` launches an OpenHands agent to reproduce, diagnose, patch the SDK, and open an upstream PR against `OpenHands/software-agent-sdk`.

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

1) **TUI** (primary):
- Create/edit LLM “profiles”
- Run tests on a profile
- View results + logs
- Trigger “auto-fix” (OpenHands agent) when failing
- Track past runs

2) **Web server + simple web page** (secondary):
- Authenticated UI for adding/editing profiles and kicking off runs
- JSON API for automation (future)

### Core flow: add model → test → (maybe) auto-fix

1) User selects “Add LLM”
2) User enters:
   - `provider` (or “auto”)
   - `model` (e.g. `anthropic/claude-sonnet-4-5-20250929`, `openai/gpt-5-mini`, `openrouter/...`)
   - `base_url` (optional)
   - credentials (API key, or provider-specific fields)
   - optional: “supports tools?”, “supports streaming?”, “responses API?” (mostly auto-detected; user override for troubleshooting)
3) User clicks “Run compatibility suite”
4) `oh-llm` runs a staged test suite (see below) using the SDK
5) UI shows a clear status per stage:
   - ✅ Pass
   - ❌ Fail (with error + captured context)
6) If fail: UI offers “Run auto-fix agent”
7) Auto-fix agent produces:
   - a reproducible minimal failing script (artifact)
   - a patch against `~/repos/agent-sdk`
   - an upstream PR URL (or a local branch if PR creation fails)
8) UI displays the PR link and a human-readable summary of what changed.

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

### Stage B — Minimal conversation run (no tool calls)

Purpose: ensure SDK’s `Agent` + `Conversation` pipeline works.

- Create `Agent(llm=..., tools=[TerminalTool])` (tools included but not required).
- `Conversation.send_message("Please echo 'Hello!'")` then `Conversation.run()`.
- Assert:
  - conversation completes,
  - at least one assistant message is produced.

### Stage C — Tool calling smoke test

Purpose: validate tool calling format and parsing (common failure mode).

- Provide a safe deterministic tool action, e.g. ask the agent to run:
  - `echo TOOL_OK` via `TerminalTool`
- Assert:
  - tool call was invoked (native or non-native conversion),
  - tool output is observed by the agent,
  - agent reports a final “TOOL_OK” in natural language.

### Stage D — Optional advanced gates (toggleable)

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

- **TUI app**: local UI for profiles and runs.
- **HTTP server**: optional API + simple web UI; includes auth.
- **Runner**: executes compatibility suite stages; collects artifacts.
- **Agent launcher**: runs OpenHands agent for auto-fix in an SDK worktree.

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
- Store secrets locally with restrictive permissions (0600).
- In the web server mode, encrypt at rest (key in env or OS keychain).
- Always redact secrets from persisted run artifacts.

SDK note: `LLMRegistry.save_profile(..., include_secrets=False)` exists and is a good building block; we can store a “profile” without secrets and supply secrets via env at runtime.

### Auth (web server)

v1 suggestion:
- single-user auth (local password) or “localhost only” binding
- later: OAuth (GitHub) if multi-user truly needed

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

1) CLI runner only (no UI): define profile format, run Stage A–C, save artifacts.
2) TUI: profile editing + run history + view logs.
3) Auto-fix agent workflow: worktree + OpenHands run + local patch output.
4) Upstream PR automation: gh integration, fork/branch management.
5) Web server: auth + basic HTML form + run endpoint.

## Open questions (need your answers)

1) **Profile model format**: should `oh-llm` reuse SDK’s `LLMRegistry` on-disk profiles (`~/.openhands/llm-profiles/*.json`), or keep its own profile store?
2) **Provider scope**: do we assume “OpenAI-compatible” + a few majors (OpenAI/Anthropic/OpenRouter), or truly anything supported by litellm?
3) **What counts as ‘works’**: are Stage A–C mandatory, or is “no tools needed” acceptable for some use cases?
4) **Auto-fix boundaries**: should the agent be allowed to change only SDK code, or also docs/examples? Can it add tests?
5) **Upstream PR target**: confirm upstream is `OpenHands/software-agent-sdk` and whether we always PR against `main`.
6) **Multi-user web server**: do you actually need multi-user auth soon, or is “localhost only” acceptable for v1?
7) **Failure classification**: do we want “credential/config error” vs “SDK bug” auto-detection before offering auto-fix?

