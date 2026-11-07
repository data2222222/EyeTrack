import json
import os

import pytest

import jev_settings
import study


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "DATA_DIR", tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return tmp_path / "config.json"


def test_save_preserves_other_config_and_status_never_returns_the_key(config):
    config.write_text(json.dumps({"classifier": {"never_send": {"domains": ["private.test"]}},
                                  "apps": {"distracting": ["discord"]}}))
    original = json.loads(config.read_text())
    assert "No Jev key" in jev_settings.key_status()
    jev_settings.save_key("  fake-test-secret  ")
    assert json.loads(config.read_text()) == dict(original, typesafe_api_key="fake-test-secret")
    assert "saved" in jev_settings.key_status()
    assert "fake-test-secret" not in jev_settings.key_status()
    if os.name != "nt":
        assert config.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("content", ["{", "[]", "null", b"\xff"])
def test_invalid_config_is_not_overwritten(config, content):
    raw = content if isinstance(content, bytes) else content.encode()
    config.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        jev_settings.save_key("fake-test-secret")
    assert config.read_bytes() == raw


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_failed_save_preserves_old_key_and_cleans_temporary_file(config, monkeypatch, operation):
    jev_settings.save_key("old-test-key")
    original = config.read_bytes()

    def fail(*args):
        raise OSError("unavailable")

    monkeypatch.setattr(jev_settings.os, operation, fail)
    with pytest.raises(OSError):
        jev_settings.save_key("new-test-key")
    assert config.read_bytes() == original
    assert list(config.parent.iterdir()) == [config]


def test_environment_precedence_is_explained_without_revealing_key(config, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-environment-secret")
    assert "Environment key in use" in jev_settings.key_status()
    assert "fake-environment-secret" not in jev_settings.key_status()
