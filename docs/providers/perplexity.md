# Perplexity — provider notes

## Official docs

- Docs home: https://docs.perplexity.ai/getting-started/overview

## OpenAI-compat notes

- Perplexity exposes OpenAI-style chat/completions interfaces, but product features and model ids are provider-specific.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://api.perplexity.ai` (confirm in docs).
- **Model ids:** Perplexity model ids differ from OpenAI names.
- **Rate limits:** quota/limit failures often appear as 429.

## Troubleshooting

- Stage A fails:
  - Verify base URL and model id; check 401/403 vs 429.
- Stage B fails:
  - Tool calling behavior depends on the model. Validate with a known-good model first.

