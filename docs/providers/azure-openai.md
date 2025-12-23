# Azure OpenAI — provider notes

## Official docs

- API reference: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/reference?view=foundry-classic
- Chat/completions concepts: https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models
- Auth: https://learn.microsoft.com/en-us/azure/ai-services/openai/reference#authentication

## OpenAI-compat notes

- Azure is *similar* to OpenAI-compatible, but not identical:
  - Requests often require an `api-version` query param.
  - Many setups use **deployment name** as the “model id”.
  - Auth is usually via an `api-key` header, not `Authorization: Bearer ...`.

## Common gotchas relevant to oh-llm

- **Base URL shape:** Azure commonly uses an endpoint like:
  - `https://<resource>.openai.azure.com/`
  - plus `/openai/deployments/<deployment>/...` paths.
- **Model name:** often the *deployment* name, not the upstream model name.
- **If Stage A fails with 404/400:** it’s frequently a wrong deployment name or missing/incorrect `api-version`.

## Troubleshooting

- Stage A fails:
  - Check `base_url` and whether your URL includes the right Azure host.
  - Confirm your deployment exists and matches the configured model/deployment id.
  - Look for `api-version` mismatch.
- Stage B fails:
  - Ensure the deployment supports the required feature set (tool calling or compatible schema).

