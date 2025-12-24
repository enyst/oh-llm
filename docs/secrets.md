# Secrets + redaction policy

## What counts as a secret

- API keys, bearer tokens, passwords, refresh tokens
- Any value that grants access (even temporary)
- Real customer/user data

## Policy (non-negotiable)

- Never commit secrets to git.
- Never paste secrets into GitHub issues/PRs, Agent Mail, or logs.
- `oh-llm` must **never** persist secret *values* to disk; it may persist:
  - env var *names* (e.g. `OPENAI_API_KEY`)
  - redacted logs/artifacts where secret values are replaced by `<REDACTED>`

## Where redaction applies in oh-llm

- CLI `--json` output (redacts configured env var values)
- Run logs: `logs/run.log`
- Artifacts under `artifacts/` (capsules, validation, agent transcripts, probe results)
- Autofix PR body artifacts

## How to use redaction correctly

- Prefer passing `--redact-env <ENV_VAR_NAME>` when running commands that may include provider errors.
- Profiles automatically include their `api_key_env` in the redaction set.

## Reviewer checklist

Before approving/merging:

- Scan changed files for:
  - `.env`, `.env.*`, `.pem`, `.key`, `id_rsa`, tokens, `Authorization:` headers
  - suspicious strings like `sk-`, `Bearer `, `api_key`, `token=`
- If tests create “fake secrets”, ensure they are:
  - unique canary strings
  - asserted to be absent from output/artifacts

## If a secret leak is suspected

1) Stop and rotate the key immediately.
2) Remove/replace the leaked value from history if it ever entered git.
3) Add/expand a canary test to prevent regressions.

