# oh-llm — AGENTS.md

General workflow guidance for agents working in this repo (tooling + collaboration). Keep project-specific build/test details in other docs once they exist.

## Beads + Agent Mail (how we use them)

**Beads** provides a lightweight, dependency-aware issue database and a CLI (`bd`) for selecting “ready work”, setting priorities, and tracking status. It complements **MCP Agent Mail**’s messaging, audit trail, and file-reservation signals.

Recommended conventions
- **Single source of truth**: Use **Beads** for task status/priority/dependencies; use **Agent Mail** for conversation, decisions, and attachments (audit).
- **Shared identifiers**: Use the Beads issue id (e.g., `oh-llm-<id>`, like `oh-llm-530` or `oh-llm-8zy`) as the Mail `thread_id` and prefix message subjects with `[oh-llm-<id>]`.
- **Reservations**: When starting a task, call `file_reservation_paths(...)` for the affected paths; include the issue id in the `reason` and release on completion.
- **Repo policy (Beads files)**: Keep `.beads/` **local-only** (do not commit). Treat Beads as a personal/local queue and use Agent Mail threads for shared visibility/coordination.
  - If we ever decide to share Beads via git, batch those updates into an existing “real” PR (never open a PR solely to update Beads status).

Typical flow (agents)
1) **Pick ready work** (Beads)
   - `bd ready --json` → choose one item (highest priority, no blockers)
2) **Reserve edit surface** (Mail)
   - `file_reservation_paths(project_key, agent_name, ["path/to/area/**"], ttl_seconds=3600, exclusive=true, reason="oh-llm-<id>")`
3) **Announce start** (Mail)
   - `send_message(..., thread_id="oh-llm-<id>", subject="[oh-llm-<id>] Start: <short title>", ack_required=true)`
4) **Work and update**
   - Reply in-thread with progress and attach artifacts/images; keep discussion to one thread per issue id
5) **Complete and release**
   - `bd close oh-llm-<id> --reason "Completed"` (Beads is status authority)
   - `release_file_reservations(project_key, agent_name, paths=["path/to/area/**"])`
   - Final Mail reply: `[oh-llm-<id>] Completed` with summary and links

Mapping cheat-sheet
- Mail `thread_id` ↔ Beads issue id (e.g., `oh-llm-<id>`)
- Mail subject: `[oh-llm-<id>] …`
- File reservation `reason`: `oh-llm-<id>`
- Commit messages (optional): include `oh-llm-<id>` for traceability

Pitfalls to avoid
- Don’t create or manage tasks in Mail; treat Beads as the single task queue.
- Always include the issue id in Mail `thread_id` to avoid ID drift across tools.

## Agent Mail (MCP) quick commands

- Server endpoint: `http://127.0.0.1:8765/mcp/` (from your local `mcp-agent-mail` repo; start with `scripts/run_server_with_token.sh` or `uv run python -m mcp_agent_mail.cli serve-http`).
- Projects use absolute paths, e.g. `project_key="$(pwd)"` or `project_key="<absolute-path-to-your-project>"`.
- Register/refresh identity: `register_agent(project_key, program, model, name, task_description?, attachments_policy?)`.
- Inbox: `fetch_inbox(project_key, agent_name, include_bodies?, limit?)`; ack with `acknowledge_message(project_key, agent_name, message_id)`.
- Send mail: `send_message(project_key, sender_name, to[], subject, body_md, thread_id?, ack_required?, importance?, attachments?)`.
- File leases: `file_reservation_paths(project_key, agent_name, paths[], ttl_seconds?, exclusive?, reason?)`; release with `release_file_reservations(...)` or renew via `renew_file_reservations(...)`.
- Discover tooling/agents: `resource://projects`, `resource://project/{slug}`, `resource://tooling/directory` (via `resources/read`).

## Pull Requests (process)

Before opening or updating a PR:
- Run the relevant local checks for the changes (tests, typecheck, lint, build/packaging if applicable).
- Ensure CI checks are green on the PR.

Reviews (do not merge without human review):
- **Required**: request review via **Agent Mail** (human reviewer).
  - Send the reviewer the PR link/number + context; set `ack_required=true`.
  - Keep review discussion in the Beads issue thread (`thread_id=<issue-id>`).
  - If branch protection requires a GitHub approval, the reviewer should also approve on GitHub, but the detailed review notes live in Mail.
- **Optional (good-to-have)**: GitHub AI reviewers (e.g., Gemini / CodeRabbit).
  - Treat them as extra eyes; do not substitute them for the human Mail review.
  - Always read/resolve their inline threads (they often comment under “Files changed”).
  - Waiting policy:
    - **Gemini-code-assist**: starts automatically upon PR creation; treat it as “one extra review” once it has posted at least two top-level comments and you’ve checked/resolved its inline threads. Re-trigger with `/gemini review` if needed.
    - **CodeRabbitAI**: only wait if its ETA is <=10 minutes (pending or rate-limited). If it would block longer than that, proceed without waiting.
- Right before merging, do a final pass on GitHub:
  - “Conversation” tab: scan top-level comments (including bots).
  - “Files changed” tab: scan/resolve inline review threads.
  - “Checks”: confirm required checks/reviews are complete (or explicitly waived per repo policy).
- Merge only when CI is green, review threads are resolved/addressed, and required branch-protection rules are satisfied.
- Repo setting note: merge commits are disabled; use **squash** (or rebase) merges.

**Optional reviewer workflow** (OpenHands “roasted” review via tmux)
- Use a clean worktree to avoid clobbering shared branches/uncommitted changes:
  ```bash
  WORKTREE="$(mktemp -d -t oh-llm-review.XXXXXX)"
  git worktree add --detach "$WORKTREE" HEAD
  ```
- Start a named tmux session and capture output to a log file:
  ```bash
  PR_NUMBER=123
  SESSION=oh_pr${PR_NUMBER}
  LOG="/tmp/${SESSION}.log"
  rm -f "$LOG"

  tmux new-session -d -s "$SESSION" -n review -c "$WORKTREE" \
    "openhands --headless --always-approve -t '/codereview-roasted pr ${PR_NUMBER}'"
  tmux pipe-pane -o -t "${SESSION}:0.0" "cat >> $LOG"

  # Optional: strip ANSI while viewing
  tail -f "$LOG" | sed -E 's/\x1B\[[0-9;]*[A-Za-z]//g'
  ```
- Send follow-ups / re-review requests to the *same* waiting session:
  ```bash
  tmux send-keys -t "${SESSION}:0.0" "Re-review PR ${PR_NUMBER} after latest commits." Enter
  ```
- Stop the session when the PR is merged:
  ```bash
  tmux kill-session -t "$SESSION"
  git worktree remove "$WORKTREE"
  ```
- Pitfalls we hit:
  - You must pass the task with `-t` (positional args are treated as subcommands).
  - `--exp` UI is noisy to log/copy (ANSI); `--headless` is easier for paste-back to Mail.
