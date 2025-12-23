from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_safe_profile_id(profile_id: str) -> str:
    profile_id = profile_id.strip()
    if not profile_id or profile_id in {".", ".."}:
        raise ValueError("Invalid profile ID.")
    if Path(profile_id).name != profile_id:
        raise ValueError("Profile IDs cannot contain path separators.")
    if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        raise ValueError("Profile IDs may only contain alphanumerics, '.', '_', or '-'.")
    return profile_id


def _ensure_safe_env_var_name(env_var_name: str) -> str:
    env_var_name = env_var_name.strip()
    if not _ENV_VAR_PATTERN.fullmatch(env_var_name):
        raise ValueError("Invalid env var name (expected [A-Za-z_][A-Za-z0-9_]*).")
    return env_var_name


def resolve_openhands_profiles_dir() -> Path:
    return Path.home() / ".openhands" / "llm-profiles"


def resolve_oh_llm_profile_metadata_dir() -> Path:
    return Path.home() / ".oh-llm" / "profiles"


@dataclass(frozen=True)
class ProfileRecord:
    profile_id: str
    model: str | None
    base_url: str | None
    api_key_env: str | None
    sdk_profile_path: Path | None
    metadata_path: Path | None

    def as_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "sdk_profile_path": str(self.sdk_profile_path) if self.sdk_profile_path else None,
            "metadata_path": str(self.metadata_path) if self.metadata_path else None,
        }


def get_openhands_profile_path(profile_id: str) -> Path:
    safe_id = _ensure_safe_profile_id(profile_id)
    return resolve_openhands_profiles_dir() / f"{safe_id}.json"


def get_oh_llm_metadata_path(profile_id: str) -> Path:
    safe_id = _ensure_safe_profile_id(profile_id)
    return resolve_oh_llm_profile_metadata_dir() / f"{safe_id}.json"


def _read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_openhands_profile(profile_id: str) -> dict[str, Any] | None:
    path = get_openhands_profile_path(profile_id)
    if not path.exists():
        return None
    return _read_json_file(path)


def load_profile_metadata(profile_id: str) -> dict[str, Any] | None:
    path = get_oh_llm_metadata_path(profile_id)
    if not path.exists():
        return None
    return _read_json_file(path)


def write_openhands_profile(
    *,
    profile_id: str,
    model: str,
    base_url: str | None,
    overwrite: bool,
) -> Path:
    safe_id = _ensure_safe_profile_id(profile_id)
    path = get_openhands_profile_path(safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Profile already exists: {safe_id} -> {path}")

    payload: dict[str, Any] = {"profile_id": safe_id, "model": model}
    if base_url:
        payload["base_url"] = base_url

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def write_profile_metadata(
    *,
    profile_id: str,
    api_key_env: str,
    overwrite: bool,
) -> Path:
    safe_id = _ensure_safe_profile_id(profile_id)
    safe_env = _ensure_safe_env_var_name(api_key_env)
    path = get_oh_llm_metadata_path(safe_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Profile metadata already exists: {safe_id} -> {path}")

    payload = {
        "schema_version": 1,
        "profile_id": safe_id,
        "api_key_env": safe_env,
        "created_at": _utc_now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def update_profile(
    *,
    profile_id: str,
    model: str | None,
    base_url: str | None,
    clear_base_url: bool,
    api_key_env: str | None,
) -> ProfileRecord:
    """Update an existing profile's non-secret fields.

    Note: this never stores secret values; `api_key_env` is only the env var name.
    """
    safe_id = _ensure_safe_profile_id(profile_id)

    sdk_path = get_openhands_profile_path(safe_id)
    meta_path = get_oh_llm_metadata_path(safe_id)

    sdk_exists = sdk_path.exists()
    meta_exists = meta_path.exists()

    sdk_payload: dict[str, Any] = {}
    if sdk_exists:
        sdk_payload = load_openhands_profile(safe_id) or {}

    meta_payload: dict[str, Any] = {}
    if meta_exists:
        meta_payload = load_profile_metadata(safe_id) or {}

    if not sdk_payload and not meta_payload:
        raise FileNotFoundError(f"Profile not found: {safe_id}")

    sdk_changed = False
    meta_changed = False

    if model is not None:
        sdk_payload["profile_id"] = safe_id
        sdk_payload["model"] = str(model)
        sdk_changed = True

    if clear_base_url:
        if not sdk_payload and not sdk_exists and model is None:
            raise ValueError("Cannot clear base_url without an existing SDK profile or --model.")
        if "model" not in sdk_payload and model is None:
            raise ValueError("SDK profile is missing 'model'; re-add or edit with --model.")
        sdk_payload.pop("base_url", None)
        sdk_changed = True
    elif base_url is not None:
        if not sdk_payload and not sdk_exists and model is None:
            raise ValueError("Cannot update base_url without an existing SDK profile or --model.")
        if "model" not in sdk_payload and model is None:
            raise ValueError("SDK profile is missing 'model'; re-add or edit with --model.")

        normalized = str(base_url).strip()
        if normalized:
            sdk_payload["base_url"] = normalized
        else:
            sdk_payload.pop("base_url", None)
        sdk_changed = True

    if api_key_env is not None:
        safe_env = _ensure_safe_env_var_name(api_key_env)
        meta_payload.setdefault("schema_version", 1)
        meta_payload["profile_id"] = safe_id
        meta_payload["api_key_env"] = safe_env
        meta_payload.setdefault("created_at", _utc_now_iso())
        meta_payload["updated_at"] = _utc_now_iso()
        meta_changed = True

    if not sdk_changed and not meta_changed:
        existing = get_profile(safe_id)
        if existing is None:
            raise FileNotFoundError(f"Profile not found: {safe_id}")
        return existing

    if sdk_changed:
        if not sdk_payload:
            raise ValueError(
                "Internal error: attempted to update SDK profile, but payload is empty."
            )
        sdk_payload.setdefault("profile_id", safe_id)
        sdk_payload.pop("api_key", None)
        if "model" not in sdk_payload:
            raise ValueError("SDK profile is missing 'model'; re-add or edit with --model.")

        sdk_path.parent.mkdir(parents=True, exist_ok=True)
        sdk_path.write_text(
            json.dumps(sdk_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        try:
            sdk_path.chmod(0o600)
        except OSError:
            pass

    if meta_changed:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        try:
            meta_path.chmod(0o600)
        except OSError:
            pass

    return get_profile(safe_id) or ProfileRecord(
        profile_id=safe_id,
        model=None,
        base_url=None,
        api_key_env=None,
        sdk_profile_path=sdk_path if sdk_path.exists() else None,
        metadata_path=meta_path if meta_path.exists() else None,
    )


def delete_profile(*, profile_id: str, missing_ok: bool = False) -> dict[str, Any]:
    safe_id = _ensure_safe_profile_id(profile_id)
    sdk_path = get_openhands_profile_path(safe_id)
    meta_path = get_oh_llm_metadata_path(safe_id)

    removed = {"sdk_profile_path": None, "metadata_path": None}
    any_removed = False

    if sdk_path.exists():
        sdk_path.unlink()
        removed["sdk_profile_path"] = str(sdk_path)
        any_removed = True

    if meta_path.exists():
        meta_path.unlink()
        removed["metadata_path"] = str(meta_path)
        any_removed = True

    if not any_removed and not missing_ok:
        raise FileNotFoundError(f"Profile not found: {safe_id}")

    return {"profile_id": safe_id, "removed": removed, "deleted": any_removed, "ok": True}


def upsert_profile(
    *,
    profile_id: str,
    model: str,
    base_url: str | None,
    api_key_env: str,
    overwrite: bool,
) -> ProfileRecord:
    sdk_path = write_openhands_profile(
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        overwrite=overwrite,
    )
    meta_path = write_profile_metadata(
        profile_id=profile_id,
        api_key_env=api_key_env,
        overwrite=overwrite,
    )
    return ProfileRecord(
        profile_id=_ensure_safe_profile_id(profile_id),
        model=model,
        base_url=base_url,
        api_key_env=_ensure_safe_env_var_name(api_key_env),
        sdk_profile_path=sdk_path,
        metadata_path=meta_path,
    )


def _extract_llm_fields(sdk_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    model = sdk_payload.get("model")
    base_url = sdk_payload.get("base_url")
    return (
        str(model) if model is not None else None,
        str(base_url) if base_url is not None else None,
    )


def _extract_env_var(meta_payload: dict[str, Any]) -> str | None:
    env_var = meta_payload.get("api_key_env")
    return str(env_var) if env_var is not None else None


def list_profiles() -> list[ProfileRecord]:
    ids: set[str] = set()

    openhands_dir = resolve_openhands_profiles_dir()
    if openhands_dir.exists():
        ids.update(path.stem for path in openhands_dir.glob("*.json"))

    meta_dir = resolve_oh_llm_profile_metadata_dir()
    if meta_dir.exists():
        ids.update(path.stem for path in meta_dir.glob("*.json"))

    records: list[ProfileRecord] = []
    for raw_id in sorted(ids):
        try:
            profile_id = _ensure_safe_profile_id(raw_id)
        except ValueError:
            continue

        sdk_path = get_openhands_profile_path(profile_id)
        meta_path = get_oh_llm_metadata_path(profile_id)

        sdk_payload = load_openhands_profile(profile_id) if sdk_path.exists() else None
        meta_payload = load_profile_metadata(profile_id) if meta_path.exists() else None

        model: str | None = None
        base_url: str | None = None
        api_key_env: str | None = None

        if sdk_payload is not None:
            model, base_url = _extract_llm_fields(sdk_payload)
        if meta_payload is not None:
            api_key_env = _extract_env_var(meta_payload)

        records.append(
            ProfileRecord(
                profile_id=profile_id,
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
                sdk_profile_path=sdk_path if sdk_path.exists() else None,
                metadata_path=meta_path if meta_path.exists() else None,
            )
        )
    return records


def get_profile(profile_id: str) -> ProfileRecord | None:
    profile_id = _ensure_safe_profile_id(profile_id)
    sdk_path = get_openhands_profile_path(profile_id)
    meta_path = get_oh_llm_metadata_path(profile_id)

    sdk_payload = load_openhands_profile(profile_id) if sdk_path.exists() else None
    meta_payload = load_profile_metadata(profile_id) if meta_path.exists() else None
    if sdk_payload is None and meta_payload is None:
        return None

    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    if sdk_payload is not None:
        model, base_url = _extract_llm_fields(sdk_payload)
    if meta_payload is not None:
        api_key_env = _extract_env_var(meta_payload)

    return ProfileRecord(
        profile_id=profile_id,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        sdk_profile_path=sdk_path if sdk_path.exists() else None,
        metadata_path=meta_path if meta_path.exists() else None,
    )
