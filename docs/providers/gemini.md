# Gemini (Google AI Studio)

## Docs

- Gemini API docs: https://ai.google.dev/gemini-api/docs
- OpenAI compatibility (Gemini API): https://ai.google.dev/gemini-api/docs/openai
- LiteLLM provider doc: https://docs.litellm.ai/docs/providers/gemini

## OpenAI compatibility endpoint

Google’s Gemini API documents an OpenAI-compatible base URL:

- `https://generativelanguage.googleapis.com/v1beta/openai/`

See: https://ai.google.dev/gemini-api/docs/openai

## Notes / quirks (vs “generic OpenAI-compatible”)

- The OpenAI compatibility layer is a compatibility surface; features (tool calling, structured output, streaming, etc.) may have provider-specific constraints—use the compatibility doc page above as your first reference.
- If you are using LiteLLM (recommended for this project), double-check the model naming/prefix rules on the LiteLLM provider page, since Gemini supports both native and OpenAI-compatible access patterns.

