# Ollama — provider notes

## Official docs

- OpenAI compatibility: https://ollama.com/blog/openai-compatibility
- Native API docs: https://github.com/ollama/ollama/blob/main/docs/api.md

## OpenAI-compat notes

- Ollama can expose OpenAI-compatible endpoints for local models.

## Common gotchas relevant to oh-llm

- **Base URL:** commonly `http://localhost:11434/v1`.
- **API key:** usually not required for local usage; `oh-llm` still expects an env var name in the profile, but in practice it can be a dummy env var for local-only testing.
- **Model ids:** typically the Ollama model name you pulled (e.g., `llama3.1`), but check your local `ollama list`.

## Troubleshooting

- Stage A fails:
  - Ensure the Ollama daemon is running and the OpenAI-compatible endpoint is enabled.
  - Confirm the model exists locally.
- Stage B fails:
  - Some local models may behave differently for tool calling; consider shorter prompts and smaller models for debugging.

