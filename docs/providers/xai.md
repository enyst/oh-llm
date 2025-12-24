# xAI — provider notes

## Official docs

- Docs home: https://docs.x.ai/ (may require a browser)

## OpenAI-compat notes

- xAI provides OpenAI-style chat/completions endpoints for Grok models (confirm exact base URL + auth in docs).

## Common gotchas relevant to oh-llm

- **Base URL:** typically an `https://.../v1` base (confirm in docs).
- **Model ids:** use the exact Grok model id.
- **Docs access:** their docs site may block non-browser clients (403 via curl); use a browser if needed.

## Troubleshooting

- Stage A fails:
  - Confirm base URL, model id, and auth header format.
- Stage B fails:
  - Validate on a known-good tool-capable model; if needed, reduce prompt complexity.

