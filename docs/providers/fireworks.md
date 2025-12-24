# Fireworks — provider notes

## Official docs

- API reference: https://docs.fireworks.ai/api-reference/introduction

## OpenAI-compat notes

- Fireworks provides OpenAI-compatible endpoints for chat/completions.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://api.fireworks.ai/inference/v1` (confirm in docs).
- **Model ids:** may require a `accounts/<...>/models/<...>`-style name depending on plan/features.
- **Streaming:** some providers are strict about streaming fields; keep payload minimal when debugging.

## Troubleshooting

- Stage A fails:
  - Check model id spelling and base URL.
  - Look for 401/403 vs 404 vs 429.
- Stage B fails:
  - Ensure the model you picked supports tool calling (or relies on SDK compatibility if applicable).

