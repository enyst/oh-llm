# OpenAI — provider notes

## Official docs

- Docs home: https://platform.openai.com/docs
- API reference: https://platform.openai.com/docs/api-reference
- Chat Completions API: https://platform.openai.com/docs/api-reference/chat
- Completions API (legacy): https://platform.openai.com/docs/api-reference/completions
- Responses API: https://platform.openai.com/docs/api-reference/responses
- Function/tool calling: https://platform.openai.com/docs/guides/function-calling
- Streaming: https://platform.openai.com/docs/api-reference/streaming

## OpenAI-compat notes (vs “generic OpenAI-style”)

- OpenAI has a legacy **Completions** API, a modern **Chat Completions** API, and a newer **Responses** API. Tooling and SDKs may choose one (or translate between them). If Stage A fails with endpoint-specific errors, confirm which endpoint the underlying SDK/provider is using.
- Tool calling is expected to work through Chat Completions/Responses. When going through LiteLLM and/or compatibility layers, validate that tool calls are being translated into the schema the SDK expects.

## Common gotchas relevant to oh-llm

- **Model naming:** ensure the exact model id string is accepted by the provider (typos can look like auth issues).
- **Rate limits/quota:** 429s can happen quickly; Stage B is more expensive than Stage A.
- **Streaming:** if you later enable optional streaming gates, providers may differ in chunk formats and error behavior.

## Troubleshooting

- Stage A fails:
  - Verify `--model` is valid for your account.
  - Verify your env var is set and the SDK is reading it (oh-llm stores only the env var name).
  - Check for 401/403 (auth), 404 (model/endpoint mismatch), 429 (quota/rate).
- Stage B fails:
  - Look for tool-call schema mismatches in logs/artifacts.
  - Try re-running with a lower iteration budget (if applicable) to reduce cost and noise.
