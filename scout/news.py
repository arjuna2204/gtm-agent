"""Leadership signals from news RSS: a new CFO / VP Finance reviews vendors in their first 90 days.

v1 uses keyword matching on headlines; Day 2 adds a Claude check that the article is really
about this company and really announces a finance leader.
"""
import email.utils
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from .net import http_get

RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
LEADER_RE = re.compile(
    r"\b(appoints?|names?|hires?|welcomes?|announces?|promotes?|joins?|tapped|taps|adds?)\b.*?"
    r"\b(chief financial officer|cfo|vp,? (of )?finance|vice president,? (of )?finance|head of finance|"
    r"finance chief|controller)\b"
    r"|\b(chief financial officer|cfo|head of finance)\b.*?\b(appointed|named|hired|joins|join)\b", re.I)


def query_url(company):
    q = f'"{company}" (CFO OR "chief financial officer" OR "VP Finance" OR "head of finance")'
    return RSS.format(q=urllib.parse.quote(q))


def parse_rss(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        pub = it.findtext("pubDate") or ""
        try:
            d = email.utils.parsedate_to_datetime(pub).date().isoformat()
        except Exception:
            d = ""
        out.append({"title": title, "url": link, "date": d,
                    "source": (src.text or "").strip() if src is not None and src.text else ""})
    return out


def leader_items(items, company, max_age_days=120, today=None):
    today = today or date.today()
    name = company.lower()
    keep = []
    for it in items:
        t = it["title"]
        if name not in t.lower() or not LEADER_RE.search(t):
            continue
        if it["date"]:
            age = (today - datetime.fromisoformat(it["date"]).date()).days
            if age > max_age_days:
                continue
        keep.append(it)
    return keep


def collect(store, max_companies=150, log=print):
    """Check news only for companies that already have another signal (keeps requests low)."""
    with_sig = {s["company_id"] for s in store.signals.values()}
    todo = sorted((c for c in store.companies.values() if c["id"] in with_sig),
                  key=lambda c: c.get("news_checked", ""))[:max_companies]
    new = 0
    for c in todo:
        c["news_checked"] = date.today().isoformat()
        status, body = http_get(query_url(c["name"]))
        if status != 200 or not body:
            continue
        try:
            items = parse_rss(body)
        except ET.ParseError:
            continue
        for it in leader_items(items, c["name"]):
            _s, is_new = store.add_signal(
                c["id"], "leader", it["url"], it["date"], it["title"], it["url"],
                detail=f"Reported by {it['source'] or 'news'}", data={"needs_check": True})
            new += is_new
    log(f"News: {len(todo)} companies checked, {new} new finance-leader signals")
    return new
