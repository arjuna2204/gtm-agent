"""Weekly run: confirm news signals, score every account, write up the top 100.

    python -m scout.weekly --top 100
    python -m scout.weekly --no-ai        # scores only, no API calls
"""
import argparse
import json

from . import score, writeups
from .store import DATA, Store, now_iso, today

# Approximate list prices per million tokens (input, output). Used only for the cost log; check current pricing.
PRICES = {"claude-haiku-5-5": (1.0, 5.0), "claude-sonnet-5-5": (3.0, 15.0)}


def cost(usage):
    usd = 0.0
    for u in usage:
        pin, pout = PRICES.get(u["model"], (3.0, 15.0))
        usd += u["in"] / 1e6 * pin + u["out"] / 1e6 * pout
    return round(usd, 4)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=100)
    p.add_argument("--no-ai", action="store_true")
    a = p.parse_args(argv)
    store = Store()
    profile = score.load_profile()
    usage = []
    if not a.no_ai:
        writeups.confirm_leaders(store, usage)
        store.save()
    rows = score.score_all(store, profile)
    score.save_scores(rows, today())
    print(f"Scored {len(rows)} accounts with at least one timing signal")
    if not a.no_ai:
        writeups.write_top(store, rows, profile, top=a.top, usage=usage)
    runs_path = DATA / "runs.json"
    runs = json.loads(runs_path.read_text()) if runs_path.exists() else []
    runs.append({"at": now_iso(), "step": "weekly", "accounts": len(rows), "calls": len(usage), "cost_usd": cost(usage)})
    runs_path.write_text(json.dumps(runs[-100:], indent=1) + "\n")
    print(f"API calls: {len(usage)}, approx cost ${cost(usage)}")


if __name__ == "__main__":
    main()
