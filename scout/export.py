"""Bundle scores, companies, signals and write-ups into one file the website reads.

    python -m scout.export          -> site/gtm/data/app.json
"""
import json

from .store import DATA, ROOT, Store, now_iso

OUT = ROOT / "site" / "gtm" / "data" / "app.json"


def _load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def build(store, max_accounts=300):
    scores = _load("scores.json", {"run_date": "", "accounts": []})
    writeups = _load("writeups.json", {})
    review = _load("review.json", {})
    stats = _load("stats.json", {})
    profile = json.loads((ROOT / "config" / "profile.json").read_text())
    by_co = {}
    for s in store.signals.values():
        by_co.setdefault(s["company_id"], []).append(s)
    accounts = []
    for row in scores["accounts"][:max_accounts]:
        c = store.companies.get(row["company_id"])
        if not c:
            continue
        sigs = sorted(by_co.get(c["id"], []), key=lambda s: s["date"] or "", reverse=True)
        used = set(row["signal_ids"])
        sigs = [s for s in sigs if s["id"] in used] + [s for s in sigs if s["id"] not in used][:5]
        w = writeups.get(c["id"])
        accounts.append({
            "id": c["id"], "name": c["name"], "city": c.get("city", ""), "state": c.get("state", ""),
            "industry": c.get("industry", ""), "size_est": c.get("size_est", ""), "stage_est": c.get("stage_est", ""),
            "open_roles": c.get("open_roles"), "board_url": c.get("board_url", ""),
            "locations": c.get("locations_sample", []),
            "rank": row["rank"], "score": row["total"], "fit": row["fit"], "timing": row["timing"],
            "strength": row["strength"], "parts": row["parts"], "reasons": row["reasons"],
            "signals": [{"id": s["id"], "type": s["type"], "date": s["date"], "title": s["title"],
                         "url": s["source_url"], "detail": s.get("detail", ""),
                         "role_class": s["data"].get("role_class", ""), "used": s["id"] in used} for s in sigs],
            "writeup": None if not w else {k: w[k] for k in ("why_now", "persona", "brief", "emails", "written_at")},
        })
    return {"generated_at": now_iso(), "scored_on": scores["run_date"], "product": profile["product"],
            "buyer": profile["buyer"], "stats": stats, "review": review, "accounts": accounts}


def main():
    app = build(Store())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Exported {len(app['accounts'])} accounts to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
