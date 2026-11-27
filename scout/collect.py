"""Daily collection run.

    python -m scout.collect all --days 5       # Form D + job boards + news
    python -m scout.collect formd --days 30    # backfill raises
    python -m scout.collect boards
    python -m scout.collect news
"""
import argparse
import csv
import json
import time

from . import ats, formd, news
from .store import DATA, Store, today


def load_seed(path=DATA / "seed_watchlist.csv"):
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_stats(store, started):
    by_type = {}
    for s in store.signals.values():
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    with_sig = {s["company_id"] for s in store.signals.values()}
    stats = {"run_at": today(), "seconds": round(time.time() - started),
             "companies": len(store.companies), "companies_with_signals": len(with_sig),
             "signals": by_type}
    (DATA / "stats.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["all", "formd", "boards", "news"])
    p.add_argument("--days", type=int, default=5, help="business days of Form D filings to scan")
    p.add_argument("--formd-limit", type=int, default=400)
    p.add_argument("--detect", type=int, default=150, help="max Form D companies to probe for job boards")
    p.add_argument("--news", type=int, default=150)
    a = p.parse_args(argv)
    started = time.time()
    store = Store()
    if a.step in ("all", "formd"):
        formd.collect(store, days=a.days, limit=a.formd_limit)
        store.save()
    if a.step in ("all", "boards"):
        ats.collect(store, load_seed(), max_detect=a.detect, today_iso=today())
        store.save()
    if a.step in ("all", "news"):
        news.collect(store, max_companies=a.news)
        store.save()
    write_stats(store, started)


if __name__ == "__main__":
    main()
