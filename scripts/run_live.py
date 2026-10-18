"""Run forever: hourly at :20 UTC, plus each user's check-in and quiet-hours end.  uv run python scripts/run_live.py"""
import os

from aqagent import db, ops
from aqagent.clock import SystemClock

ops.load_dotenv()
engine = db.make_engine(os.environ.get("DATABASE_URL", ops.DEFAULT_DB))
ops.init_db(engine)
ops.seed(engine, SystemClock().now())
print("running: hourly at :20 UTC, plus check-ins and quiet-hours ends (Ctrl+C to stop)")
ops.build_scheduler(engine, ops.openaq_client(), ops.llm_from_env(), blocking=True).start()
