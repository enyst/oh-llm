# Groq — provider notes

## Official docs

- Docs home: https://console.groq.com/docs
- OpenAI-compatible API: https://console.groq.com/docs/openai

## OpenAI-compat notes

- Groq exposes an OpenAI-compatible API; differences usually show up in model availability, limits, and some response fields.

## Common gotchas relevant to oh-llm

- **Model ids:** Groq model ids differ from OpenAI; confirm in Groq docs.
- **Rate limits / throughput:** Groq is fast but still rate-limited; Stage B can hit limits if repeated.

## Troubleshooting

- Stage A fails:
  - Verify key + model id.
- Stage B fails:
  - Check whether tool calling is supported by the specific model; if not, rely on the SDK compatibility layer and ensure prompts are explicit.
