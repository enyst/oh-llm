# OpenRouter — provider notes

## Official docs

- Docs home: https://openrouter.ai/docs
- API reference (includes OpenAI-compatible endpoints): https://openrouter.ai/docs/api/reference
- Streaming reference: https://openrouter.ai/docs/api/reference/streaming

## OpenAI-compat notes

- OpenRouter is explicitly OpenAI-compatible at the HTTP layer, but model naming and routing are provider-specific.
- Some features depend on the underlying model/provider chosen via OpenRouter.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://openrouter.ai/api/v1` (confirm in docs).
- **Model ids:** OpenRouter model ids often look like `provider/model` (varies).
- **Headers:** OpenRouter supports optional headers for ranking/attribution; keep them out of artifacts.

## Troubleshooting

- Stage A fails:
  - Confirm base URL and model id.
  - Check 401/403 vs 404.
- Stage B fails:
  - Tool calling behavior depends on the underlying model; try a different model if unsure.
