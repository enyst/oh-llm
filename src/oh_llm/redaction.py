from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

REDACTED = "<REDACTED>"

_SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
}


def _looks_secret_key_name(key: str) -> bool:
    return key.strip().lower() in _SECRET_KEY_NAMES


@dataclass(frozen=True)
class Redactor:
    secret_values: tuple[str, ...] = ()

    def redact_text(self, text: str) -> str:
        if not text:
            return text

        redacted = text

        for value in self.secret_values:
            if value:
                redacted = redacted.replace(value, REDACTED)

        redacted = re.sub(
            r"(?i)(authorization\s*:\s*bearer)\s+[A-Za-z0-9\-._=+/]+",
            r"\1 " + REDACTED,
            redacted,
        )
        redacted = re.sub(r"\bsk-[A-Za-z0-9]{20,}\b", REDACTED, redacted)

        return redacted

    def redact_obj(self, obj: Any) -> Any:
        if obj is None:
            return None

        if isinstance(obj, str):
            return self.redact_text(obj)

        if isinstance(obj, list):
            return [self.redact_obj(item) for item in obj]

        if isinstance(obj, tuple):
            return [self.redact_obj(item) for item in obj]

        if isinstance(obj, dict):
            redacted: dict[str, Any] = {}
            for key, value in obj.items():
                key_str = str(key)
                if _looks_secret_key_name(key_str):
                    redacted[key_str] = REDACTED
                else:
                    redacted[key_str] = self.redact_obj(value)
            return redacted

        return obj

    def redact_json(self, obj: Any) -> str:
        return json.dumps(self.redact_obj(obj), sort_keys=True, indent=2) + "\n"


def redactor_from_env_vars(*env_var_names: str) -> Redactor:
    values: list[str] = []
    for name in env_var_names:
        value = os.environ.get(name)
        if value:
            values.append(value)
    return Redactor(secret_values=tuple(values))

