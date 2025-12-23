# Together — provider notes

## Official docs

- OpenAI API compatibility: https://docs.together.ai/docs/openai-api-compatibility
- Docs home: https://docs.together.ai/

## OpenAI-compat notes

- Together provides an OpenAI-compatible API for many hosted models.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://api.together.xyz/v1` (confirm in docs).
- **Model ids:** Together model ids often look like `provider/model` and must match exactly.

## Troubleshooting

- Stage A fails:
  - Confirm base URL + model id and watch for 401/403 vs 404.
- Stage B fails:
  - Some models behind Together may not support tool calling reliably; try an alternate model.

