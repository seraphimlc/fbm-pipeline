#!/usr/bin/env python3
"""Shared config loading for the GPT image helper scripts."""
import json
import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
BACKEND_ENV_PATH = REPO_ROOT / "backend" / ".env"
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.json"
LOCAL_CONFIG_PATH = SCRIPT_DIR / "config.local.json"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_config() -> dict:
    config = _load_json(DEFAULT_CONFIG_PATH)
    backend_env = _parse_env_file(BACKEND_ENV_PATH)

    if backend_env.get("GPT_IMAGE_USE_LLM_API", "").lower() == "true":
        env_config = {
            "api_key": backend_env.get("LLM_API_KEY"),
            "base_url": backend_env.get("LLM_API_BASE"),
            "model": backend_env.get("GPT_IMAGE_MODEL"),
        }
    else:
        env_config = {
            "api_key": backend_env.get("GPT_IMAGE_API_KEY"),
            "base_url": backend_env.get("GPT_IMAGE_API_BASE"),
            "model": backend_env.get("GPT_IMAGE_MODEL"),
        }
    env_config["default_size"] = backend_env.get("GPT_IMAGE_DEFAULT_SIZE")

    for key, value in env_config.items():
        if value:
            config[key] = value

    config.update({k: v for k, v in _load_json(LOCAL_CONFIG_PATH).items() if v})

    process_env = {
        "api_key": os.getenv("GPT_IMAGE_API_KEY"),
        "base_url": os.getenv("GPT_IMAGE_API_BASE"),
        "model": os.getenv("GPT_IMAGE_MODEL"),
        "default_size": os.getenv("GPT_IMAGE_DEFAULT_SIZE"),
    }
    for key, value in process_env.items():
        if value:
            config[key] = value

    if not config.get("api_key") or config.get("api_key") == "YOUR_API_KEY_HERE":
        raise RuntimeError(
            "Missing GPT image API key. Set GPT_IMAGE_API_KEY, backend/.env, "
            "or scripts/config.local.json."
        )
    return config
