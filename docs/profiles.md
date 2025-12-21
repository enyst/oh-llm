# Profiles

`oh-llm` stores **non-secret** model configuration in the same on-disk format used by the OpenHands agent SDK (`LLMRegistry`).

## Where files live

- SDK profile (no secrets): `~/.openhands/llm-profiles/<profile_id>.json`
- `oh-llm` metadata (env var name only): `~/.oh-llm/profiles/<profile_id>.json`

Why two files?

The SDK profile schema forbids unknown fields, so `oh-llm` cannot embed an “API key env var name” inside the SDK profile JSON. `oh-llm` keeps that single extra piece of data in its own metadata file.

## CLI

Create a profile without storing secrets:

```bash
export MY_LLM_API_KEY="..."
uv run oh-llm profile add demo --model gpt-5-mini --base-url https://example.invalid --api-key-env MY_LLM_API_KEY
```

Inspect:

```bash
uv run oh-llm profile list
uv run oh-llm profile show demo --json
```

