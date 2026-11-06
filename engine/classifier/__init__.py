"""Goal-aware surface classifier (Jev with a local fallback). The engine only needs `build_default`."""

from .service import JevClassifier, Settings, build_classifier, build_default
from .types import Surface

__all__ = ["JevClassifier", "Settings", "Surface", "build_classifier", "build_default"]
