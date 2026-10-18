"""One hourly run now: ingest from OpenAQ (backfilling on first run), decide, clock tick.  uv run python scripts/tick_once.py"""
import json
import os

from aqagent import db, ops
from aqagent.clock import SystemClock

ops.load_dotenv()
engine = db.make_engine(os.environ.get("DATABASE_URL", ops.DEFAULT_DB))
ops.init_db(engine)
ops.seed(engine, SystemClock().now())
print(json.dumps(ops.tick(engine, SystemClock(), ops.openaq_client(), ops.llm_from_env()), default=str, indent=2))
