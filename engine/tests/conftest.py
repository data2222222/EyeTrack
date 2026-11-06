"""Lets the tests import the engine's sibling packages (`classifier`) the way engine.py does."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
