## Summary

## Testing

- [ ] `uv run ruff check .`
- [ ] `uv run pytest -m unit`
- [ ] `uv run pytest -m e2e <path>` (if applicable)

## Secrets checklist

- [ ] No secret values in diff (API keys/tokens/passwords)
- [ ] `.env` is not committed
- [ ] If artifacts are included, they are redacted

See `docs/secrets.md`.

