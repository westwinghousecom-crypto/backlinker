"""Measure how many Appwrite reads and writes the running app makes while idle.

    .venv\\Scripts\\python scripts\\measure_usage.py [seconds=180]

Starts the real application (all workers) against the real Appwrite configured in backend/.env, leaves it idle, and reports
the request rate over the steady-state part of the run (the first 60 seconds are warm-up and excluded) plus a monthly
projection. Nothing is submitted, so any call counted here is overhead, not customer work.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.usage import usage  # noqa: E402
from app.main import app  # noqa: E402

WARMUP = 60


def main(seconds: int) -> None:
    with TestClient(app):  # runs the real lifespan: indexing, check and Google workers start polling
        time.sleep(WARMUP)
        before = usage.snapshot()
        time.sleep(max(seconds - WARMUP, 30))
        after = usage.snapshot()
    span = after["seconds"] - before["seconds"]
    reads, writes = after["reads"] - before["reads"], after["writes"] - before["writes"]
    by_call = {k: after["by_call"].get(k, 0) - before["by_call"].get(k, 0) for k in after["by_call"]}
    per_month = lambda n: round(n / span * 86400 * 30)  # noqa: E731
    print(f"steady-state window: {span:.0f} s idle")
    print(f"reads : {reads} requests  ->  {per_month(reads):,} per 30 days  (Free allowance 500,000)")
    print(f"writes: {writes} requests  ->  {per_month(writes):,} per 30 days  (Free allowance 250,000)")
    print("by call:", {k: v for k, v in by_call.items() if v})


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 180)
