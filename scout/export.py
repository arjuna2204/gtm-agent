"""Bundle companies, signals, demo scores and demo write-ups into one file the website reads.

    python -m scout.export          -> site/gtm/data/app.json

The website re-scores every company in the browser for whatever product and buyer the visitor
describes, so the export carries all companies that have at least one signal, not just the demo top list.
"""
import json
from datetime import date, timedelta

from .store import DATA, ROOT, Store, now_iso

OUT = ROOT / "site" / "gtm" / "data" / "app.json"
HIRING_FRESH_DAYS = 21
TEAM_LABELS = {"finance": "Finance", "sales": "Sales", "marketing": "Marketing", "engineering": "Engineering",
               "data": "Data", "security_it": "Security & IT", "people": "People & HR",
               "customer": "Customer success", "operations": "Operations", "legal": "Legal"}


def _load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def _team(s):
    d = s.get("data", {})
    if d.get("team"):
        return d["team"]
    return "finance" if d.get("role_class") else ""


def build(store, today=None):
    today = today or date.today()
    fresh_cut = (today - timedelta(days=HIRING_FRESH_DAYS)).isoformat()
    scores = _load("scores.json", {"run_date": "", "accounts": []})
    demo = {r["company_id"]: r for r in scores["accounts"]}
    writeups = _load("writeups.json", {})
    profile = json.loads((ROOT / "config" / "profile.json").read_text())

    by_co = {}
    for s in store.signals.values():
        if s["type"] == "hiring" and s.get("last_seen", "")[:10] < fresh_cut:
            continue  # role no longer on the board
        if s["type"] == "leader" and s["data"].get("confirmed") is not True:
            continue  # unconfirmed headline
        by_co.setdefault(s["company_id"], []).append(s)

    companies = []
    for cid, sigs in by_co.items():
        c = store.companies.get(cid)
        if not c:
            continue
        sigs.sort(key=lambda s: s["date"] or "", reverse=True)
        d = demo.get(cid)
        w = writeups.get(cid)
        companies.append({
            "id": cid, "name": c["name"], "city": c.get("city", ""), "state": c.get("state", ""),
            "industry": c.get("industry", ""), "size_est": c.get("size_est", ""), "stage_est": c.get("stage_est", ""),
            "open_roles": c.get("open_roles"), "board_url": c.get("board_url", ""),
            "locations": c.get("locations_sample", []), "team_counts": c.get("team_counts", {}),
            "signals": [{"id": s["id"], "type": s["type"], "date": s["date"], "title": s["title"],
                         "url": s["source_url"], "detail": s.get("detail", ""), "team": _team(s),
                         "key": bool(s["data"].get("key") or s["data"].get("role_class") == "stack"),
                         "amount": s["data"].get("amount")} for s in sigs],
            "demo": None if not d else {"rank": d["rank"], "score": d["total"]},
            "writeup": None if not w else {k: w[k] for k in ("why_now", "persona", "brief", "emails", "written_at")},
        })
    companies.sort(key=lambda x: (x["demo"] or {}).get("rank", 10**6))
    by_type = {}
    for c in companies:
        for s in c["signals"]:
            by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    return {"generated_at": now_iso(), "scored_on": scores["run_date"], "demo_product": profile["product"],
            "demo_buyer": profile["buyer"], "team_labels": TEAM_LABELS, "signal_counts": by_type,
            "review": _load("review.json", {}), "companies": companies}


def main():
    app = build(Store())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(app, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Exported {len(app['companies'])} companies ({OUT.stat().st_size // 1024} KB) to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
