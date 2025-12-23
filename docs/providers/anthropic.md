# Anthropic (Claude) — provider notes

## Official docs

- Docs home: https://docs.anthropic.com/
- API reference: https://docs.anthropic.com/en/api
- Messages API: https://docs.anthropic.com/en/api/messages
- Tool use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- Streaming: https://docs.anthropic.com/en/api/messages-streaming

## OpenAI-compat notes

- Anthropic’s native API is **not** OpenAI’s schema; OpenAI-compat behavior typically comes from a translation layer (e.g. LiteLLM).
- Tool calling (“tool use”) has its own structure. If Stage B fails, it’s often because translation between OpenAI-style tool calls and Anthropic tool-use blocks is imperfect.

## Common gotchas relevant to oh-llm

- **Auth:** Anthropic uses its own API keys; ensure the correct env var is used for this profile.
- **System prompts:** Anthropic has explicit system/content conventions; translation layers may map these differently.
- **Tool calling determinism:** Some models/providers require very explicit prompts to reliably trigger tools.

## Troubleshooting

- Stage A fails:
  - Confirm your base URL and provider routing are correct in LiteLLM (if used).
  - Check for 401/403 vs 404 (model id not found / wrong routing).
- Stage B fails:
  - Inspect the recorded tool-call details: did the agent *intend* to call a tool but no tool invocation was produced?
  - Try simplifying tool schema (fewer/shorter tool descriptions) if you control it.
