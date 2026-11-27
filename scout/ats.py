"""Hiring signals from public job boards (Greenhouse, Lever, Ashby).

A company opening a Controller / FP&A / Accounts Payable / finance-ops role is building its
finance stack: the moment it buys spend, AP and accounting tools.
"""
import re
import urllib.parse

from ._ats_parsers import PARSERS, board_url
from .net import http_get_json
from .store import clean_name

ATS_LIST = ("ashby", "greenhouse", "lever")

# Roles that mean "a finance function is being built or rebuilt" (strongest signal).
STACK_ROLES = re.compile(
    r"\b(controller|comptroller|fp&a|fp & a|financial planning|accounts payable|\bap\b|procure[- ]to[- ]pay|"
    r"head of finance|vp,? (of )?finance|vice president,? finance|director,? finance|finance director|"
    r"chief financial officer|\bcfo\b|finance operations|finance ops|finops|revenue operations accountant|"
    r"procurement|spend|expense|treasury)\b", re.I)
# Any finance / accounting role (weaker signal).
FINANCE_ROLES = re.compile(
    r"\b(accountant|accounting|bookkeep|payroll|finance|financial analyst|billing|tax|audit|"
    r"revenue accountant|staff accountant|controller)\b", re.I)
# Titles that contain finance words but are about the product, not the company's own finance team.
NOT_INTERNAL = re.compile(
    r"\b(engineer|engineering|developer|software|product manager|designer|sales|account executive|"
    r"customer success|solutions|implementation|support|recruit|marketing|data scientist)\b", re.I)


# Internships and student programs don't signal a finance team being built.
INTERN = re.compile(r"\b(intern|internship|co-op|summer \d{4}|campus|new grad)\b", re.I)


def classify_title(title):
    """Return 'stack', 'finance' or '' for a job title. Day 2 adds a Claude check for ambiguous ones."""
    t = title or ""
    if NOT_INTERNAL.search(t) or INTERN.search(t):
        return ""
    if STACK_ROLES.search(t):
        return "stack"
    if FINANCE_ROLES.search(t):
        return "finance"
    return ""


# ---------------------------------------------------------------- hiring by team (any product)
# Order matters: the first team whose pattern matches wins.
TEAMS = [
    ("legal", re.compile(r"\b(counsel|legal|paralegal|attorney|lawyer|contracts manager)\b", re.I)),
    ("people", re.compile(r"\b(recruit\w*|talent|people|human resources|\bhr\b|hrbp|benefits|total rewards|"
                          r"compensation|payroll)\b", re.I)),
    ("security_it", re.compile(r"\b(security|ciso|\bit\b|information technology|helpdesk|help desk|"
                               r"sysadmin|systems administrator|endpoint|identity|iam|grc)\b", re.I)),
    ("data", re.compile(r"\b(data|analytics|machine learning|\bml\b|\bai\b|bi developer|business intelligence)\b", re.I)),
    ("customer", re.compile(r"\b(customer success|customer support|support|implementation|onboarding|"
                            r"customer experience|\bcx\b|solutions consultant|technical account manager)\b", re.I)),
    ("sales", re.compile(r"\b(sales|account executive|\bae\b|business development|\bbdr\b|\bsdr\b|"
                         r"partnerships?|account manager|revenue operations|revops|channel)\b", re.I)),
    ("marketing", re.compile(r"\b(marketing|growth|demand gen\w*|brand|content|seo|communications|"
                             r"\bpr\b|product marketing|lifecycle|social media|events)\b", re.I)),
    ("engineering", re.compile(r"\b(engineer\w*|developer|\bsre\b|devops|platform|infrastructure|architect|"
                               r"software|firmware|frontend|backend|full[- ]stack|mobile|qa)\b", re.I)),
    ("operations", re.compile(r"\b(operations|bizops|business operations|strategy|chief of staff|"
                              r"procurement|supply chain|logistics|facilities|workplace)\b", re.I)),
]
TEAM_LABELS = {"finance": "Finance", "sales": "Sales", "marketing": "Marketing", "engineering": "Engineering",
               "data": "Data", "security_it": "Security & IT", "people": "People & HR", "customer": "Customer success",
               "operations": "Operations", "legal": "Legal"}
LEAD = re.compile(r"\b(head of|vp|v\.p\.|vice president|director|chief|lead|manager|principal|staff|founding|first)\b", re.I)
TEAM_KEY = re.compile(r"\b(operations|ops|enablement|platform|infrastructure|devops|sre|security|people ops|"
                      r"benefits|demand gen\w*|data engineer|analytics engineer|procurement)\b", re.I)


def classify_team(title):
    """Return (team, is_key_role) or (None, False). Key roles = leaders and the people who
    run a team's tools and processes: the hires that come right before a team buys software."""
    t = title or ""
    if INTERN.search(t):
        return None, False
    fin = classify_title(t)
    if fin:
        return "finance", fin == "stack"
    for team, pat in TEAMS:
        if pat.search(t):
            return team, bool(LEAD.search(t) or TEAM_KEY.search(t))
    return None, False


def _url(ats, slug):
    url = board_url(ats, slug)
    return url.replace("?content=true", "") if ats == "greenhouse" else url


def fetch_board(ats, slug, company):
    """Return (ok, jobs)."""
    status, data = http_get_json(_url(ats, slug))
    if ats == "greenhouse" and (status != 200 or not isinstance(data, dict)):
        status, data = http_get_json(_url(ats, slug).replace("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"))
    ok = isinstance(data, list) if ats == "lever" else isinstance(data, dict) and isinstance(data.get("jobs"), list)
    if status != 200 or not ok:
        return False, []
    return True, PARSERS[ats](data, company, slug)


def candidate_slugs(name, strict=False):
    """Likely board slugs for a company name. strict=True (used for Form D legal names)
    skips the risky first-word-only guess, which causes false matches like 'atlas'."""
    words = re.findall(r"[a-z0-9]+", clean_name(name).lower())
    cands = ["".join(words), "-".join(words)]
    if not strict and len(words) > 1 and len(words[0]) >= 5:
        cands.append(words[0])
    out = []
    for c in cands:
        if c and c not in out and len(c) >= 3:
            out.append(c)
    return out


def detect_board(name, strict=False):
    """Try likely slugs on each ATS; keep the board with the most jobs. Returns (ats, slug, jobs) or None."""
    best = None
    for slug in candidate_slugs(name, strict):
        for ats in ATS_LIST:
            ok, jobs = fetch_board(ats, slug, name)
            if ok and (best is None or len(jobs) > len(best[2])):
                best = (ats, slug, jobs)
    return best


def hiring_summary(jobs):
    stack = [j for j in jobs if classify_title(j["title"]) == "stack"]
    fin = [j for j in jobs if classify_title(j["title"]) == "finance"]
    return stack, fin


def size_band_from_jobs(n_open):
    """Very rough size proxy from open roles. Labelled approximate everywhere it is shown."""
    if n_open >= 60:
        return "500+"
    if n_open >= 20:
        return "200-500"
    if n_open >= 6:
        return "50-200"
    return "under 50"


def record_board(store, cid, ats, slug, jobs, today_iso):
    c = store.companies[cid]
    c.update({"ats": ats, "ats_slug": slug, "open_roles": len(jobs),
              "size_est": size_band_from_jobs(len(jobs)),
              "board_url": f"https://jobs.ashbyhq.com/{slug}" if ats == "ashby"
              else f"https://job-boards.greenhouse.io/{slug}" if ats == "greenhouse"
              else f"https://jobs.lever.co/{slug}"})
    locs = [j["location"] for j in jobs if j.get("location")]
    if locs and not c.get("locations_sample"):
        c["locations_sample"] = sorted(set(locs))[:5]
    # Classify every open role by team. Keep all finance roles (the demo product's buyer) and, for other
    # teams, up to 3 key roles (leaders, ops/platform owners) or 1 regular role, to keep the dataset small.
    by_team, counts = {}, {}
    for j in jobs:
        team, key = classify_team(j["title"])
        if not team:
            continue
        counts[team] = counts.get(team, 0) + 1
        by_team.setdefault(team, []).append((j, key))
    c["team_counts"] = counts
    keep = []
    for team, items in by_team.items():
        if team == "finance":
            keep += [(team, j, key) for j, key in items]
            continue
        keys = [(team, j, True) for j, key in items if key][:3]
        keep += keys or [(team, items[0][0], False)]
    new = n_stack = n_fin = 0
    for team, j, key in keep:
        role_class = ("stack" if key else "finance") if team == "finance" else ""
        n_stack += role_class == "stack"
        n_fin += role_class == "finance"
        posted = (j.get("posted") or "")[:10] or today_iso
        _s, is_new = store.add_signal(
            cid, "hiring", j["id"], posted, f"Hiring: {j['title']}", j.get("url") or c["board_url"],
            detail=f"{j.get('location') or 'location n/a'}; {j.get('department') or 'team n/a'}",
            data={"role_class": role_class, "team": team, "key": key, "title": j["title"], "ats": ats,
                  "job_id": j["id"]})
        new += is_new
    return n_stack, n_fin, new


def collect(store, seed_rows, max_detect=150, today_iso="", log=print):
    """Poll boards for seed companies (known boards) and detect boards for Form D companies."""
    polled = detected = new = 0
    for r in seed_rows:
        if r.get("status", "ok") not in ("ok", "") or r.get("ats") not in ATS_LIST:
            continue
        c = store.upsert_company(r["company"], source="watchlist")
        ok, jobs = fetch_board(r["ats"], r["slug"], r["company"])
        if not ok:
            continue
        polled += 1
        _s, _f, n = record_board(store, c["id"], r["ats"], r["slug"], jobs, today_iso)
        new += n
    todo = [c for c in store.companies.values() if "formd" in c["sources"] and not c.get("ats_checked")]
    for c in todo[:max_detect]:
        c["ats_checked"] = today_iso
        found = detect_board(c.get("legal_name") or c["name"], strict=True)
        if not found:
            continue
        ats, slug, jobs = found
        detected += 1
        _s, _f, n = record_board(store, c["id"], ats, slug, jobs, today_iso)
        new += n
    log(f"Job boards: {polled} seed boards polled, {detected} new boards found for Form D companies, {new} new hiring signals")
    return new


def board_slug_from_url(url):
    m = re.search(r"(?:jobs\.ashbyhq\.com|greenhouse\.io|jobs\.lever\.co)/([A-Za-z0-9_.-]+)", url or "")
    return urllib.parse.unquote(m.group(1)) if m else ""
