# Anthropic (Claude)

## Docs

- Anthropic platform docs: https://platform.claude.com/docs/
- Messages API reference: https://platform.claude.com/docs/claude/reference/messages_post
- LiteLLM provider doc: https://docs.litellm.ai/docs/providers/anthropic

## Notes / quirks (vs “generic OpenAI-compatible”)

- Anthropic’s native API is not an OpenAI Chat Completions endpoint; LiteLLM adapts OpenAI-style requests to the Anthropic Messages API.
- Tool calling exists natively in Anthropic, but the underlying representation (tool blocks, schema fields, etc.) differs from OpenAI; when debugging tool-call issues, compare the transformed payloads against the Messages API spec.
- Parameter requirements (e.g. token limits, system instructions placement) can differ from other providers; prefer the platform docs above when interpreting errors.

