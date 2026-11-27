"""Rubric scoring (code, not the model, so scores are consistent and explainable).

| Component                   | Max | Rule |
| Fit: industry               | 15  | include list 15, adjacent or unknown 8, else 0 |
| Fit: size                   | 15  | in target bands 15, next band over/under 8, else 0 |
| Fit: region                 | 10  | US address or US job locations 10 |
| Timing: recent raise        | 20  | <30d 20, 30-90d 14, 90-180d 6 |
| Timing: finance hiring      | 15  | open stack role 15, other finance role 8 |
| Timing: new finance leader  | 10  | confirmed CFO/VP Finance news <=120d |
| Signal strength             | 15  | 5 per distinct signal type |
"""
import json
import re
from datetime import date, datetime, timedelta

from .store import DATA, ROOT

BANDS = ["under 50", "50-200", "200-500", "500+"]
STAGE_TO_BAND = {"Seed": "under 50", "Series A": "50-200", "Series B": "50-200", "Series C+": "200-500"}
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
US_LOC = re.compile(r"\b(united states|usa|u\.s\.|remote[ -]?(us|usa)|new york|san francisco|los angeles|chicago|boston|"
                    r"austin|seattle|miami|denver|atlanta|washington,? dc|nyc|sf bay|" + "|".join(
                        f", {s}" for s in US_STATES) + r")\b", re.I)
HIRING_FRESH_DAYS = 21
HIRING_MAX_AGE_DAYS = 120  # a role posted long ago and still open is a weak "now" signal  # a role counts only if it was still on the board this recently


def load_profile(path=ROOT / "config" / "profile.json"):
    return json.loads(path.read_text())


def _days_since(iso, today):
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except (TypeError, ValueError):
        return None


def score_company(c, sigs, profile, today=None):
    today = today or date.today()
    buyer = profile["buyer"]
    parts, reasons, used = {}, {}, []

    ind = c.get("industry", "")
    if ind and ind in buyer["industries_include"]:
        parts["industry"], reasons["industry"] = 15, f"{ind} is a target industry"
    elif not ind or ind in buyer["industries_adjacent"]:
        parts["industry"], reasons["industry"] = 8, f"{ind or 'Industry unknown'}: partial credit"
    else:
        parts["industry"], reasons["industry"] = 0, f"{ind} is outside the target industries"

    size, how = c.get("size_est", ""), "estimated from open roles"
    if not size and c.get("stage_est") in STAGE_TO_BAND:
        size, how = STAGE_TO_BAND[c["stage_est"]], "estimated from raise size"
    if size in buyer["size_bands"]:
        parts["size"], reasons["size"] = 15, f"About {size} people ({how})"
    elif size and any(abs(BANDS.index(size) - BANDS.index(b)) == 1 for b in buyer["size_bands"] if size in BANDS):
        parts["size"], reasons["size"] = 8, f"About {size} people, next to the target range ({how})"
    else:
        parts["size"], reasons["size"] = 0, "Size unknown or outside range"

    locs = " | ".join(c.get("locations_sample", []))
    us = c.get("state") in US_STATES or bool(US_LOC.search(locs))
    parts["region"], reasons["region"] = (10, "US-based") if us else (0, "No US location found")

    fresh_cut = (today - timedelta(days=HIRING_FRESH_DAYS)).isoformat()
    raises = [s for s in sigs if s["type"] == "raise"]
    hires = [s for s in sigs if s["type"] == "hiring" and s.get("last_seen", "")[:10] >= fresh_cut
             and (_days_since(s["date"], today) or 0) <= HIRING_MAX_AGE_DAYS]
    leaders = [s for s in sigs if s["type"] == "leader" and s["data"].get("confirmed") is True
               and (_days_since(s["date"], today) or 999) <= 120]

    parts["raise"], reasons["raise"] = 0, "No raise in the funding window"
    if raises:
        best = min(raises, key=lambda s: _days_since(s["date"], today) or 9999)
        d = _days_since(best["date"], today)
        if d is not None and d <= buyer["funding_window_days"]:
            pts = 20 if d < 30 else 14 if d <= 90 else 6
            parts["raise"], reasons["raise"] = pts, f"{best['title']}, {d} days ago"
            used.append(best["id"])

    stack = [s for s in hires if s["data"].get("role_class") == "stack"]
    if stack:
        parts["hiring"], reasons["hiring"] = 15, "Hiring " + ", ".join(s["data"]["title"] for s in stack[:3])
        used += [s["id"] for s in stack[:3]]
    elif hires:
        parts["hiring"], reasons["hiring"] = 8, "Hiring " + ", ".join(s["data"]["title"] for s in hires[:3])
        used += [s["id"] for s in hires[:3]]
    else:
        parts["hiring"], reasons["hiring"] = 0, "No open finance roles"

    if leaders:
        parts["leader"], reasons["leader"] = 10, leaders[0]["title"]
        used.append(leaders[0]["id"])
    else:
        parts["leader"], reasons["leader"] = 0, "No new finance leader found"

    types = {t for t, k in (("raise", "raise"), ("hiring", "hiring"), ("leader", "leader")) if parts[k] > 0}
    parts["strength"] = 5 * len(types)
    reasons["strength"] = f"{len(types)} independent signal type(s)"

    total = sum(parts.values())
    timing = parts["raise"] + parts["hiring"] + parts["leader"]
    return {"company_id": c["id"], "total": total, "fit": parts["industry"] + parts["size"] + parts["region"],
            "timing": timing, "strength": parts["strength"], "parts": parts, "reasons": reasons,
            "signal_ids": used, "has_timing_signal": timing > 0}


def score_all(store, profile, today=None):
    by_co = {}
    for s in store.signals.values():
        by_co.setdefault(s["company_id"], []).append(s)
    rows = [score_company(c, by_co.get(cid, []), profile, today) for cid, c in store.companies.items()]
    rows = [r for r in rows if r["has_timing_signal"]]
    rows.sort(key=lambda r: (-r["total"], -r["timing"], r["company_id"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def save_scores(rows, run_date):
    (DATA / "scores.json").write_text(json.dumps({"run_date": run_date, "accounts": rows}, indent=1) + "\n")
