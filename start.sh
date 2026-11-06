#!/bin/sh
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/engine/.venv/bin/python" "$here/engine/engine.py" "$@"
