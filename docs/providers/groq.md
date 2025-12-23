# Groq

## Docs

- OpenAI compatibility guide: https://console.groq.com/docs/openai
- General docs: https://console.groq.com/docs
- LiteLLM provider doc: https://docs.litellm.ai/docs/providers/groq

## OpenAI-compatible base URL

Groq documents an OpenAI-compatible base URL:

- `https://api.groq.com/openai/v1`

See: https://console.groq.com/docs/openai

## Notes / quirks (vs “generic OpenAI-compatible”)

- Groq presents an OpenAI-compatible surface, but supported models, rate limits, and any provider-specific constraints should be taken from Groq’s docs (links above).
- When debugging tool calling or streaming behavior, confirm the provider’s current OpenAI-compatibility coverage and compare with what LiteLLM sends/receives.

