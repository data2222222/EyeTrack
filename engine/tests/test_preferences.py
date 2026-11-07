import json

import pytest

import preferences
import study


def test_missing_preferences_use_fresh_defaults_without_creating_files(tmp_path):
    path = tmp_path / "missing" / "preferences.json"
    loaded = preferences.load_preferences(path)
    assert loaded == preferences.DEFAULTS
    loaded["sounds_enabled"] = False
    assert preferences.load_preferences(path)["sounds_enabled"] is True
    assert not path.parent.exists()


def test_default_path_follows_study_data_dir_at_call_time(tmp_path, monkeypatch):
    for directory in (tmp_path / "first", tmp_path / "second"):
        monkeypatch.setattr(study, "DATA_DIR", directory)
        saved = preferences.save_preferences({"sound_volume": 73})
        assert json.loads((directory / "preferences.json").read_text()) == saved
        assert preferences.load_preferences() == saved


@pytest.mark.parametrize("content", ["{", "null", "[]", '"text"', "123", b"\xff"])
def test_malformed_files_fall_back_to_defaults(tmp_path, content):
    path = tmp_path / "preferences.json"
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    assert preferences.load_preferences(path) == preferences.DEFAULTS


@pytest.mark.parametrize("name", [
    "sounds_enabled", "sound_checkins", "sound_completion", "camera_enabled", "show_preview",
])
@pytest.mark.parametrize("value", [0, 1, "false", None, [], {}])
def test_booleans_require_actual_booleans(name, value):
    assert preferences.validate_preferences({name: value})[name] is True
    assert preferences.validate_preferences({name: False})[name] is False


@pytest.mark.parametrize("name,minimum,maximum", [
    ("sound_volume", 0, 100), ("work_minutes", 1, 120), ("break_minutes", 1, 60),
])
def test_integer_bounds_reject_bad_values_without_coercion(name, minimum, maximum):
    for value in (minimum - 1, maximum + 1, True, False, 2.0, "2", None, [], {}):
        assert preferences.validate_preferences({name: value})[name] == preferences.DEFAULTS[name]
    for value in (minimum, maximum):
        assert preferences.validate_preferences({name: value})[name] == value


@pytest.mark.parametrize("name,choices", [
    ("mode", ("pc", "both")), ("sound_style", ("chime", "bell", "soft")),
    ("alert_strictness", ("light", "strict", "asian_parent")),
])
def test_choices_are_validated(name, choices):
    for value in choices:
        assert preferences.validate_preferences({name: value})[name] == value
    for value in ("unknown", "notebook", None, [], {}, 1):
        assert preferences.validate_preferences({name: value})[name] == preferences.DEFAULTS[name]


def test_supported_rhythms_and_custom_lengths_roundtrip(tmp_path):
    path = tmp_path / "preferences.json"
    for work_minutes, break_minutes in (*study.RHYTHMS, (37, 7)):
        values = dict(preferences.DEFAULTS, work_minutes=work_minutes, break_minutes=break_minutes)
        assert preferences.save_preferences(values, path) == values
        assert preferences.load_preferences(path) == values


def test_save_filters_unknown_fields_and_does_not_mutate_input(tmp_path):
    path = tmp_path / "nested" / "preferences.json"
    values = {"sound_volume": 90, "sound_style": [], "unknown": "ignored"}
    original = values.copy()
    saved = preferences.save_preferences(values, path)
    assert saved == dict(preferences.DEFAULTS, sound_volume=90)
    assert preferences.load_preferences(path) == saved
    assert json.loads(path.read_text()) == saved
    assert values == original
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_atomic_save_failure_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch, operation):
    path = tmp_path / "preferences.json"
    preferences.save_preferences({"sound_volume": 20}, path)
    original = path.read_bytes()

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(preferences.os, operation, fail)
    with pytest.raises(OSError, match="disk unavailable"):
        preferences.save_preferences({"sound_volume": 80}, path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_load_permission_errors_propagate(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise PermissionError("cannot read")

    monkeypatch.setattr(preferences.Path, "open", fail)
    with pytest.raises(PermissionError, match="cannot read"):
        preferences.load_preferences(tmp_path / "preferences.json")


def test_save_directory_errors_propagate(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("occupied")
    with pytest.raises(OSError):
        preferences.save_preferences({}, path / "preferences.json")
