"""Classifier tests. Fake Jev backend and fake embedder: no network, no model download."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from classifier import JevClassifier, build_classifier
from classifier.jev import JevResult
from classifier.keys import make_key, state_text
from classifier.local import LocalScorer, load_embedder
from classifier.types import Clock, Surface

GOAL = "write the spec"


def browser(
    domain: str = "youtube.com", title: str = "A video", url: str | None = None, **kw
) -> Surface:
    return Surface(
        kind="browser",
        app="Google Chrome",
        window_title=f"{title} - Chrome",
        domain=domain,
        url=url or f"https://{domain}/watch",
        page_title=title,
        **kw,
    )


class FakeJev:
    """Records requests; answers are gated on an event so tests can observe the pending state."""

    def __init__(self, result: JevResult | Exception | None = None) -> None:
        self.result = result or JevResult("distraction", 0.9)
        self.states: list[str] = []
        self.gate = threading.Event()
        self.gate.set()
        self.done = threading.Event()

    def ask(self, state: str) -> JevResult:
        self.states.append(state)
        self.gate.wait(5)
        try:
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        finally:
            self.done.set()


class FakeEmbedder:
    """Maps texts to fixed 2D unit vectors so cosines are predictable."""

    def __init__(self, vectors: dict[str, tuple[float, float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = [
            np.array(self.vectors.get(t, (0.0, 1.0)), dtype=np.float32) for t in texts
        ]
        return np.stack([r / np.linalg.norm(r) for r in rows])


def make(
    tmp_path: Path, backend: FakeJev | None, clock: Clock | None = None, **settings
) -> JevClassifier:
    return build_classifier(
        tmp_path,
        {"jev_enabled": False, **settings},
        backend=backend,
        embedder=FakeEmbedder({}),
        clock=clock or Clock(frozen_ms=1_000_000),
    )


def wait_idle(clf: JevClassifier) -> None:
    deadline = time.monotonic() + 5
    while clf._inflight and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not clf._inflight


def settle(clf: JevClassifier, backend: FakeJev) -> None:
    """Wait for the background request to finish and its bookkeeping to land."""
    assert backend.done.wait(5)
    wait_idle(clf)


# ---------------------------------------------------------------- keys


def test_key_includes_goal_and_title_hash_and_ignores_query():
    a = make_key("goal a", browser(title="Intro"))
    assert a != make_key("goal b", browser(title="Intro"))
    assert a != make_key("goal a", browser(title="Other"))
    assert a == make_key(
        "goal a",
        browser(title="  (3) INTRO ", url="https://youtube.com/watch?v=secret#t=5"),
    )
    assert a.startswith("browser:youtube.com|")
    # two chats with the same generic title are different pages
    chat = browser("chatgpt.com", "ChatGPT", url="https://chatgpt.com/c/one")
    assert make_key("goal a", chat) != make_key(
        "goal a", browser("chatgpt.com", "ChatGPT", url="https://chatgpt.com/c/two"))


def test_state_text_sends_title_once():
    text = state_text(GOAL, Surface("browser", "Chrome", "Capacitors - Google Search", "google.com",
                                    "https://google.com/search", "Capacitors - Google Search"))
    assert "Page title: Capacitors - Google Search" in text and "Window title" not in text
    assert "Window title: Notes" in state_text(GOAL, Surface("app", "Obsidian", "Notes"))


def test_state_text_capped_and_query_stripped():
    s = browser(title="t" * 500, url="https://youtube.com/watch/x/y/z/w?token=abc#frag")
    text = state_text("g" * 500, s)
    assert len(text) <= 600
    assert "token" not in text and "frag" not in text


# ---------------------------------------------------------------- routing


def test_novel_surface_is_pending_then_cached(tmp_path):
    backend = FakeJev(JevResult("distraction", 0.9))
    backend.gate.clear()
    clf = make(tmp_path, backend)
    first = clf.classify(GOAL, browser())
    assert first.pending and first.source == "local"
    backend.gate.set()
    settle(clf, backend)
    second = clf.classify(GOAL, browser())
    assert (second.category, second.source, second.confidence, second.pending) == (
        "distraction",
        "jev",
        0.9,
        False,
    )
    assert len(backend.states) == 1


def test_inflight_requests_are_deduped(tmp_path):
    backend = FakeJev()
    backend.gate.clear()
    clf = make(tmp_path, backend)
    for _ in range(3):
        clf.classify(GOAL, browser())
    backend.gate.set()
    settle(clf, backend)
    assert len(backend.states) == 1


@pytest.mark.parametrize(
    ("confidence", "cached"),
    [(0.95, True), (0.8, True), (0.5, True), (0.49, False)],
)
def test_confidence_routing(tmp_path, confidence, cached):
    backend = FakeJev(JevResult("distraction", confidence))
    clf = make(tmp_path, backend)
    clf.classify(GOAL, browser())
    settle(clf, backend)
    result = clf.classify(GOAL, browser())
    if cached:
        assert result.source == "jev" and result.confidence == confidence
    else:
        assert (
            result.source == "local" and not result.pending
        )  # discarded, not re-asked this tick


def test_total_failure_marks_unreachable_and_uses_local(tmp_path):
    backend = FakeJev(TimeoutError())
    clf = make(tmp_path, backend)
    clf.classify(GOAL, browser())
    settle(clf, backend)
    result = clf.classify(GOAL, browser())
    assert result.source == "local" and result.remote_unreachable and not result.pending
    assert len(backend.states) == 1  # cooldown: no hammering


def test_no_backend_is_local_only_and_unreachable(tmp_path):
    result = make(tmp_path, None).classify(GOAL, browser())
    assert result.source == "local" and result.remote_unreachable and not result.pending


@pytest.mark.parametrize("title", [None, "", "   "])
def test_no_title_is_not_sent_or_cached(tmp_path, title):
    backend = FakeJev()
    clf = make(tmp_path, backend)
    loading = Surface("browser", "Chrome", title, "google.com", "https://google.com/search", title)
    result = clf.classify(GOAL, loading)
    assert result.source == "local" and not result.pending
    assert backend.states == []


def test_no_goal_does_nothing(tmp_path):
    backend = FakeJev()
    clf = make(tmp_path, backend)
    result = clf.classify("  ", browser())
    assert result.category is None and result.source is None and not result.pending
    assert backend.states == []


# ---------------------------------------------------------------- never-send


@pytest.mark.parametrize(
    "surface",
    [
        browser("example.com", incognito=True),
        browser("accounts.bitwarden.com"),
        browser("chase.com"),
        Surface(kind="app", app="1Password", window_title="Vault"),
        Surface(
            kind="app",
            app="Google Chrome",
            window_title="New tab - Google Chrome (Incognito)",
        ),
        browser("custom-bank.example"),
    ],
)
def test_never_send(tmp_path, surface):
    backend = FakeJev()
    clf = build_classifier(
        tmp_path,
        {"jev_enabled": False, "never_send": {"domains": ["custom-bank.example"]}},
        backend=backend,
        embedder=None,
    )
    result = clf.classify(GOAL, surface)
    assert (result.category, result.source) == ("neutral", "private")
    assert backend.states == []


def test_user_apps_pattern(tmp_path):
    clf = build_classifier(
        tmp_path,
        {"jev_enabled": False, "never_send": {"apps": ["Obsidian"]}},
        backend=FakeJev(),
        embedder=None,
    )
    assert (
        clf.classify(GOAL, Surface(kind="app", app="Obsidian", window_title="x")).source
        == "private"
    )


# ---------------------------------------------------------------- overrides & persistence


def test_override_beats_cache_and_private_and_persists(tmp_path):
    backend = FakeJev(JevResult("distraction", 0.9))
    clf = make(tmp_path, backend)
    surface = browser()
    key = clf.classify(GOAL, surface).key
    settle(clf, backend)
    clf.set_override(key, "productive")
    result = clf.classify(GOAL, surface)
    assert (result.category, result.source) == ("productive", "override")

    reloaded = make(tmp_path, FakeJev())
    assert reloaded.classify(GOAL, surface).source == "override"
    assert (
        reloaded.classify(GOAL, browser(title="Other")).source == "local"
    )  # not an override
    assert any(r["source"] == "override" for r in reloaded.cache_entries())


def test_cache_persists_across_restart_and_expires(tmp_path):
    clock = Clock(frozen_ms=1_000_000)
    backend = FakeJev()
    clf = make(tmp_path, backend, clock)
    clf.classify(GOAL, browser())
    settle(clf, backend)
    assert json.loads((tmp_path / "classifications.json").read_text())["entries"]

    page = browser("github.com", "repo")
    clf.classify(GOAL, page)
    settle(clf, backend)
    clock.frozen_ms = 1_000_000 + 20 * 3_600_000
    assert make(tmp_path, FakeJev(), clock).classify(GOAL, page).source == "cache"
    clock.frozen_ms = 1_000_000 + 25 * 3_600_000
    assert make(tmp_path, FakeJev(), clock).classify(GOAL, page).source == "local"


@pytest.mark.parametrize("domain", ["youtube.com", "www.google.com", "en.wikipedia.org", "claude.ai", "chatgpt.com"])
def test_mixed_sites_expire_after_two_hours(tmp_path, domain):
    clock = Clock(frozen_ms=1_000_000)
    backend = FakeJev()
    clf = make(tmp_path, backend, clock)
    clf.classify(GOAL, browser(domain))
    settle(clf, backend)
    clock.frozen_ms += 2 * 3_600_000 - 1000
    assert clf.classify(GOAL, browser(domain)).source == "jev"
    clock.frozen_ms += 2000
    assert clf.classify(GOAL, browser(domain)).source == "local"   # expired: asks Jev again


def test_goal_change_means_new_key(tmp_path):
    backend = FakeJev()
    clf = make(tmp_path, backend)
    clf.classify("goal a", browser())
    settle(clf, backend)
    assert clf.classify("goal a", browser()).source == "jev"
    assert (
        clf.classify("goal b", browser()).source == "local"
    )  # fresh key, asks Jev again


# ---------------------------------------------------------------- coalescing


def test_hourly_cap_never_reuses_another_pages_verdict(tmp_path):
    clock = Clock(frozen_ms=1_000_000)
    backend = FakeJev(JevResult("distraction", 0.9))
    clf = make(tmp_path, backend, clock, hourly_cap=3)
    for i in range(3):
        backend.done.clear()
        clf.classify(GOAL, browser("google.com", f"search {i}"))
        assert backend.done.wait(5)
        clock.frozen_ms += 1000
    wait_idle(clf)

    # over the cap: the new search keeps the list category, not the last search's "distraction"
    fourth = clf.classify(GOAL, browser("google.com", "capacitor charging - Google Search"))
    assert fourth.source == "local" and not fourth.pending
    assert len(backend.states) == 3

    # a different domain is unaffected, and the hour rolls off
    assert clf.classify(GOAL, browser("github.com", "repo")).pending
    clock.frozen_ms += 3_600_000
    assert make(tmp_path, FakeJev(), clock, hourly_cap=3).classify(GOAL, browser("google.com", "next")).pending


# ---------------------------------------------------------------- config


def test_api_key_from_env_then_config(monkeypatch):
    from classifier.service import resolve_api_key

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert resolve_api_key({}) is None
    assert resolve_api_key({"typesafe_api_key": " k1 "}) == "k1"
    monkeypatch.setenv("TYPESAFE_API_KEY", "k2")
    assert resolve_api_key({"typesafe_api_key": "k1"}) == "k2"


# ---------------------------------------------------------------- local tier


def test_local_scoring_rules():
    scorer = LocalScorer(None, g_hi=0.5, margin=0.1)
    assert (
        scorer.verdict(g=0.6, d=0.9).category == "productive"
    )  # on topic wins even near an anchor
    assert scorer.verdict(g=0.1, d=0.5).category == "distraction"
    assert (
        scorer.verdict(g=0.1, d=0.15).category == "neutral"
    )  # unrelated is not a distraction
    assert scorer.verdict(g=0.4, d=0.6).category == "distraction"
    far, near = scorer.verdict(0.1, 0.9), scorer.verdict(0.1, 0.22)
    assert far.confidence > near.confidence and far.confidence < 0.8


def test_local_scorer_with_fake_embedder():
    emb = FakeEmbedder(
        {
            "goal": (1, 0),
            "on topic": (1, 0.1),
            "playing games": (0, 1),
            "fun": (0.1, 1),
            "mail": (1, 1),
        }
    )
    scorer = LocalScorer(emb, g_hi=0.8, margin=0.3)
    assert scorer.score("goal", "on topic").category == "productive"
    assert scorer.score("goal", "fun").category == "distraction"
    assert scorer.score("goal", "mail").category == "neutral"


def test_missing_model_is_neutral_low_confidence(tmp_path):
    assert load_embedder(tmp_path) is None
    verdict = LocalScorer(None, 0.2, 0.1).score("g", "t")
    assert verdict.category == "neutral" and verdict.confidence < 0.5


# ---------------------------------------------------------------- real model


FIXTURES = Path(__file__).parent / "fixtures" / "surfaces.json"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"


@pytest.mark.skipif(
    not (MODEL_DIR / "model.onnx").exists(), reason="run python -m classifier.fetch_model"
)
def test_local_tier_accuracy_on_fixtures(tmp_path):
    embedder = load_embedder(MODEL_DIR)
    assert embedder is not None
    clf = build_classifier(tmp_path, {"jev_enabled": False}, embedder=embedder)
    rows = json.loads(FIXTURES.read_text())
    wrong, flips = [], 0
    for row in rows:
        surface = Surface(**row["surface"])
        got = clf._local_answer("k", row["goal"], surface, pending=False).category
        if got != row["expected"]:
            wrong.append(
                (
                    row["surface"].get("domain") or row["surface"]["app"],
                    row["expected"],
                    got,
                )
            )
            flips += {got, row["expected"]} == {"productive", "distraction"}
    assert len(wrong) / len(rows) <= 0.15, wrong
    assert flips == 0, wrong
