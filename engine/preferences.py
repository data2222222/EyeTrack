"""Validated desktop preferences with atomic, local-only persistence.

Malformed fields fall back independently to defaults, without coercion. Session
lengths support the standard rhythms and custom work/break minutes in 1..120 and
1..60 respectively. Missing or malformed files use defaults; other filesystem
errors propagate so the UI can explain storage failures.
"""
import json
import os
from collections.abc import Mapping
from pathlib import Path
import tempfile

import blocklist


DEFAULTS = {
    "sounds_enabled": True,
    "sound_volume": 35,
    "sound_style": "chime",
    "sound_checkins": True,
    "sound_completion": True,
    "alert_strictness": "strict",
    "camera_enabled": True,
    "show_preview": True,
    "work_minutes": 25,
    "break_minutes": 5,
    "mode": "pc",
    "blocked_sites": [],
    "blocked_apps": [],
}
_LISTS = {"blocked_sites": blocklist.clean_sites, "blocked_apps": blocklist.clean_apps}
SOUND_STYLES = ("chime", "bell", "soft")
_INTEGER_BOUNDS = {
    "sound_volume": (0, 100),
    "work_minutes": (1, 120),
    "break_minutes": (1, 60),
}
_CHOICES = {"sound_style": SOUND_STYLES, "mode": ("pc", "both"),
            "alert_strictness": ("light", "strict", "asian_parent")}


def validate_preferences(values):
    """Return a fresh, complete preferences dict, ignoring unknown fields."""
    validated = {name: list(v) if isinstance(v, list) else v for name, v in DEFAULTS.items()}
    if not isinstance(values, Mapping):
        return validated
    for name, default in DEFAULTS.items():
        value = values.get(name, default)
        if name in _LISTS:
            # a malformed list falls back to empty; individually invalid entries are dropped
            validated[name] = _LISTS[name](value)
            continue
        if type(default) is bool:
            valid = type(value) is bool
        elif name in _INTEGER_BOUNDS:
            minimum, maximum = _INTEGER_BOUNDS[name]
            valid = type(value) is int and minimum <= value <= maximum
        else:
            valid = isinstance(value, str) and value in _CHOICES[name]
        if valid:
            validated[name] = value
    return validated


def _preferences_path(path):
    if path is not None:
        return Path(path)
    import study

    return Path(study.DATA_DIR) / "preferences.json"


def load_preferences(path=None):
    """Load validated preferences; resolve study.DATA_DIR at each call."""
    try:
        with _preferences_path(path).open(encoding="utf-8") as source:
            values = json.load(source)
    except (FileNotFoundError, ValueError, UnicodeError):
        values = None
    return validate_preferences(values)


def save_preferences(values, path=None):
    """Atomically replace preferences, returning only successfully saved values.

    Invalid fields use defaults, not previous values. Pass the complete current
    preferences when updating a subset. Write/replace failures are not swallowed.
    """
    validated = validate_preferences(values)
    destination = _preferences_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(validated, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
    return validated
