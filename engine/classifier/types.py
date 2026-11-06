"""Plain types shared by the classifier modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Category = Literal["productive", "neutral", "distraction"]
# "private" = never-send surface: never sent to Jev or embedded, always neutral.
ClassificationSource = Literal["jev", "cache", "local", "override", "private"]
SurfaceKind = Literal["browser", "app"]


@dataclass(frozen=True, slots=True)
class Surface:
    """What the user is looking at."""

    kind: SurfaceKind
    app: str | None
    window_title: str | None
    domain: str | None = None  # browser only
    url: str | None = None  # browser only, query/fragment stripped, depth-capped
    page_title: str | None = None  # browser only
    incognito: bool = False

    @property
    def label(self) -> str:
        """Short human label."""
        if self.kind == "browser" and self.domain:
            return self.domain
        return self.app or "unknown"


@dataclass(frozen=True, slots=True)
class Classification:
    """Classifier result."""

    key: str  # cache key, includes a goal hash
    category: Category | None  # None while unresolved
    source: ClassificationSource | None
    confidence: float | None  # 0..1
    pending: bool  # True while a remote (Jev) answer is outstanding
    stale: bool = False  # coalesced domain-level answer: reused from another page of the same domain
    remote_unreachable: bool = False  # Jev confirmed down or not configured
    ts: int = 0


@dataclass(slots=True)
class Clock:
    """Injectable time source so the classifier is testable."""

    offset_ms: int = 0
    frozen_ms: int | None = field(default=None)

    def now_ms(self) -> int:
        if self.frozen_ms is not None:
            return self.frozen_ms
        import time

        return int(time.time() * 1000) + self.offset_ms
