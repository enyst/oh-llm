# Google Gemini (AI Studio) — provider notes

## Official docs

- Gemini API docs home: https://ai.google.dev/gemini-api/docs
- API reference: https://ai.google.dev/api
- Models + limits: https://ai.google.dev/gemini-api/docs/models
- Function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Streaming: https://ai.google.dev/gemini-api/docs/streaming
- OpenAI compatibility: https://ai.google.dev/gemini-api/docs/openai
- LiteLLM provider notes: https://docs.litellm.ai/docs/providers/gemini

## API shape + compatibility notes

- Gemini’s native APIs have their own request/response formats; OpenAI-compat behavior usually comes via a translation layer (e.g. LiteLLM).
- Function/tool calling exists, but schema differences can surface when using OpenAI-style tool definitions.
- Gemini is often more sensitive to safety/policy behavior than OpenAI-style “echo” prompts; keep Stage A/B prompts benign and deterministic.

## Common gotchas relevant to oh-llm

- **Base URL (OpenAI-compatible):** `https://generativelanguage.googleapis.com/v1beta/openai/` (per Gemini OpenAI compatibility docs).
- **Model ids:** Gemini model strings differ from OpenAI style; ensure the provider routing layer expects the same id you pass.
- **Safety blocks / policy refusals:** some prompts may trigger safety behavior; prefer deterministic, benign prompts for Stage A/B.

## Troubleshooting

- Stage A fails:
  - Verify the API key env var is set.
  - Confirm the model id matches the Gemini API’s supported list.
- Stage B fails:
  - Inspect whether tool calls were produced; if not, try a more explicit “run `echo TOOL_OK`” style prompt.
