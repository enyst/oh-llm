# DeepSeek — provider notes

## Official docs

- API docs: https://api-docs.deepseek.com/

## OpenAI-compat notes

- DeepSeek provides OpenAI-style endpoints for chat/completions. Model ids are provider-specific.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `https://api.deepseek.com/v1` (confirm in docs).
- **Model ids:** ensure you’re using the exact DeepSeek model id.
- **Rate limits / quotas:** failures may present as 429/403.

## Troubleshooting

- Stage A fails:
  - Verify base URL + model id; inspect 401 vs 404 vs 429.
- Stage B fails:
  - If tool calling fails, verify the model supports tool calling or that the SDK compat layer is taking effect.

