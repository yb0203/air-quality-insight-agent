"""Replay the shipped 90-day sample into data/replay.db and print the report.  uv run python scripts/replay_sample.py [days]"""
import json
import sys

from aqagent import ops

ops.load_dotenv()
days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
out = ops.replay_sample(f"sqlite:///{ops.ROOT / 'data' / 'replay.db'}", days, "demo", ops.llm_from_env())
print(json.dumps(out, default=str, indent=2))
