"""Write-only Jev credential settings, separate from ordinary preferences.

Preserve all other configuration and refuse to overwrite malformed files. The
saved credential is never returned to the UI or included in an error message.
"""
import json
import os
from pathlib import Path
import tempfile

import study


def config_path():
    return Path(study.DATA_DIR) / "config.json"


def key_status():
    if os.environ.get("TYPESAFE_API_KEY", "").strip():
        return "Environment key in use. It takes priority over a saved key."
    try:
        config = json.loads(config_path().read_text(encoding="utf-8"))
        if isinstance(config, dict) and config.get("typesafe_api_key"):
            return "A Jev key is saved. It is never displayed here."
    except FileNotFoundError:
        pass
    except (OSError, ValueError, UnicodeError):
        return "Couldn't read Jev configuration."
    return "No Jev key saved. Local and site-list fallbacks remain available."


def save_key(key):
    key = key.strip()
    if not key:
        raise ValueError("A key is required")
    path = config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("Invalid configuration")
    config["typesafe_api_key"] = key
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".config.", suffix=".tmp", delete=False) as temporary:
            temporary_path = temporary.name
            json.dump(config, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
