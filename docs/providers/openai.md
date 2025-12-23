# OpenAI

## Docs

- Platform docs: https://platform.openai.com/docs/
- API reference: https://platform.openai.com/docs/api-reference
- OpenAPI spec (useful for exact request/response fields): https://github.com/openai/openai-openapi
- LiteLLM provider doc: https://docs.litellm.ai/docs/providers/openai

## Notes / quirks (vs “generic OpenAI-compatible”)

- OpenAI has multiple API surfaces (notably Chat Completions vs the newer Responses API); check which one your client/library targets.
- Tool calling is supported; schemas and JSON mode/structured output behaviors are defined by OpenAI docs and can differ from other providers’ “OpenAI-compatible” implementations.
- When debugging, prefer looking at the exact HTTP request/response shape (OpenAPI spec link above) and compare with what LiteLLM emits for a given model prefix.

