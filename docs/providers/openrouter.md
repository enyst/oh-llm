# OpenRouter

## Docs

- Quickstart / API usage: https://openrouter.ai/docs/quickstart
- API reference / guides: https://openrouter.ai/docs
- LiteLLM provider doc: https://docs.litellm.ai/docs/providers/openrouter

## OpenAI-compatible base URL

OpenRouter documents an OpenAI-compatible API base:

- `https://openrouter.ai/api/v1`
- Chat Completions endpoint: `https://openrouter.ai/api/v1/chat/completions`

See: https://openrouter.ai/docs/quickstart

## Notes / quirks (vs “generic OpenAI-compatible”)

- OpenRouter uses OpenAI-compatible request/response shapes, but models are commonly referenced with provider-qualified names (for example `openai/gpt-4o`). See the OpenRouter model docs for the canonical naming.
- OpenRouter documents optional headers used for attribution/rankings:
  - `HTTP-Referer: <YOUR_SITE_URL>` (optional)
  - `X-Title: <YOUR_SITE_NAME>` (optional)
  These appear in the Quickstart examples.

