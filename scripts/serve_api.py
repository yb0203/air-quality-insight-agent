"""Serve the API on http://127.0.0.1:8000 over DATABASE_URL (default: the replay database).  uv run python scripts/serve_api.py"""
import os

import uvicorn

from aqagent import db, ops
from aqagent.api import create_app
from aqagent.clock import SystemClock

ops.load_dotenv()
url = os.environ.get("DATABASE_URL", f"sqlite:///{ops.ROOT / 'data' / 'replay.db'}")
uvicorn.run(create_app(db.make_engine(url), SystemClock()), host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
