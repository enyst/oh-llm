# OpenRouter — provider notes

## Official docs

- Docs home: https://openrouter.ai/docs
- API reference (includes OpenAI-compatible endpoints): https://openrouter.ai/docs/api/reference
- Streaming reference: https://openrouter.ai/docs/api/reference/streaming
- LiteLLM provider notes: https://docs.litellm.ai/docs/providers/openrouter

## API shape + compatibility notes

- OpenRouter is explicitly OpenAI-compatible at the HTTP layer, but model naming/routing are provider-specific.
- Some features (especially tool calling) depend on the underlying model/provider behind a given OpenRouter model id.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://openrouter.ai/api/v1` (confirm in docs).
- **Model ids:** OpenRouter model ids often look like `provider/model` (varies).
- **Optional headers:** OpenRouter supports extra headers (attribution / routing); avoid including them in logs/artifacts unless needed for debugging.
- **Provider-specific quirks:** if a model fails tool calling on OpenRouter, confirm whether the underlying provider supports the needed features.

## Troubleshooting

- Stage A fails:
  - Confirm base URL and model id.
  - Check 401/403 vs 404.
- Stage B fails:
  - Tool calling behavior depends on the underlying model; try a different model if unsure.
