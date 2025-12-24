# Mistral — provider notes

## Official docs

- API reference: https://docs.mistral.ai/api

## OpenAI-compat notes

- Mistral is generally OpenAI-compatible for chat/completions at the HTTP layer.
- Some features/fields may differ subtly from OpenAI; prefer minimal payloads when debugging.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://api.mistral.ai/v1` (confirm in docs).
- **Model ids:** use the exact Mistral model id (`mistral-...`), not marketing names.

## Troubleshooting

- Stage A fails:
  - Confirm base URL, model id, and that the API key env var is set.
- Stage B fails:
  - If tool calling fails, verify the model supports tools (or that the SDK compat behavior is engaged).

