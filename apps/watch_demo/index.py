"""Vercel entrypoint: exposes the watch demo as a module-level `app`, in fixture mode.

Vercel's Python runtime looks for a top-level `app` in `index.py` at the project root
(Root Directory `apps/watch_demo`). The demo builds its app with a factory, so this file
just calls it. Fixture and scenario paths are pinned to this folder so they resolve the
same whether `watch_demo` is imported from `src/` or from an installed wheel.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
os.environ.setdefault("WATCH_DEMO_FIXTURES", str(HERE / "fixtures"))
os.environ.setdefault("WATCH_DEMO_SCENARIOS", str(HERE / "scenarios.yaml"))

from watch_demo.app import create_app  # noqa: E402

app = create_app()
