# DeepInfra — provider notes

## Official docs

- Docs home: https://deepinfra.com/docs

## OpenAI-compat notes

- DeepInfra exposes OpenAI-compatible APIs for many hosted models; model ids are typically provider-specific.

## Common gotchas relevant to oh-llm

- **Base URL:** check the DeepInfra docs for the OpenAI-compatible base URL for your account/project.
- **Model ids:** often look like `org/model` (varies).
- **Anti-bot / docs rendering:** their docs site may require a browser to view; rely on CLI/API error messages and headers.

## Troubleshooting

- Stage A fails:
  - Confirm base URL and model id.
  - Distinguish 401/403 (auth) from 404 (model/base URL) and 429 (quota).
- Stage B fails:
  - Tool calling behavior is model-dependent; try another model family if needed.

