"""Job-board parsers copied from job-agent/finder.py (Greenhouse, Lever, Ashby)."""
import urllib.parse
from datetime import datetime, timezone

from .net import html_to_text


def ms_to_iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return ""


def board_url(ats, slug):
    q = urllib.parse.quote(slug, safe="")
    if ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{q}/jobs?content=true"
    if ats == "lever":
        return f"https://api.lever.co/v0/postings/{q}?mode=json"
    if ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{q}?includeCompensation=true"
    raise ValueError(ats)


def parse_greenhouse(data, company, slug):
    out = []
    for j in (data or {}).get("jobs", []) or []:
        loc = (j.get("location") or {}).get("name", "") or ""
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) or [] if o.get("name"))
        depts = ", ".join(d.get("name", "") for d in j.get("departments", []) or [] if d.get("name"))
        out.append({
            "id": f"greenhouse:{slug}:{j.get('id')}",
            "company": company, "ats": "greenhouse", "slug": slug,
            "title": (j.get("title") or "").strip(),
            "location": loc or offices,
            "remote": int("remote" in (loc + " " + offices).lower()),
            "department": depts,
            "url": j.get("absolute_url", ""),
            "apply_url": j.get("absolute_url", ""),
            "posted": j.get("first_published") or j.get("updated_at") or "",
            "description": html_to_text(j.get("content", ""))[:20000],
            "compensation": "",
        })
    return out


def parse_lever(data, company, slug):
    out = []
    if not isinstance(data, list):
        return out
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or ([cats.get("location")] if cats.get("location") else [])
        loc = " | ".join(l for l in locs if l)
        wt = (j.get("workplaceType") or "").lower()
        desc = j.get("descriptionPlain") or html_to_text(j.get("description", ""))
        for lst in j.get("lists", []) or []:
            desc += "\n\n" + (lst.get("text") or "") + "\n" + html_to_text(lst.get("content", ""))
        desc += "\n\n" + (j.get("additionalPlain") or "")
        sal = j.get("salaryRange") or {}
        comp = ""
        if sal.get("min") or sal.get("max"):
            comp = f"{sal.get('currency', '')} {sal.get('min', '')}-{sal.get('max', '')} {sal.get('interval', '')}".strip()
        out.append({
            "id": f"lever:{slug}:{j.get('id')}",
            "company": company, "ats": "lever", "slug": slug,
            "title": (j.get("text") or "").strip(),
            "location": loc,
            "remote": int(wt == "remote" or "remote" in loc.lower()),
            "department": ", ".join(x for x in [cats.get("department"), cats.get("team")] if x),
            "url": j.get("hostedUrl", ""),
            "apply_url": j.get("applyUrl") or j.get("hostedUrl", ""),
            "posted": ms_to_iso(j.get("createdAt")) if j.get("createdAt") else "",
            "description": desc.strip()[:20000],
            "compensation": comp,
        })
    return out


def parse_ashby(data, company, slug):
    out = []
    for j in (data or {}).get("jobs", []) or []:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        for s in j.get("secondaryLocations", []) or []:
            if isinstance(s, dict) and s.get("location"):
                locs.append(s["location"])
        loc = " | ".join(l for l in locs if l)
        wt = (j.get("workplaceType") or "").lower()
        comp = ((j.get("compensation") or {}).get("compensationTierSummary")) or ""
        out.append({
            "id": f"ashby:{slug}:{j.get('id')}",
            "company": company, "ats": "ashby", "slug": slug,
            "title": (j.get("title") or "").strip(),
            "location": loc,
            # Ashby's isRemote flag is set on many hybrid/office roles, so rely on workplaceType + location text
            "remote": int(wt == "remote" or "remote" in loc.lower()),
            "department": ", ".join(x for x in [j.get("department"), j.get("team")] if x),
            "url": j.get("jobUrl", ""),
            "apply_url": j.get("applyUrl") or j.get("jobUrl", ""),
            "posted": j.get("publishedAt") or "",
            "description": (j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")))[:20000],
            "compensation": comp,
        })
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}
