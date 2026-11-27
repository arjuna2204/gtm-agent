"""SEC Form D collector.

A Form D is filed by a private company within 15 days of the first sale in an exempt
offering (a fundraise). It is free, structured, and public: the best free "just raised" signal.

1. EDGAR daily form index lists every filing of the day:
   https://www.sec.gov/Archives/edgar/daily-index/YYYY/QTRn/form.YYYYMMDD.idx
2. Each Form D's structured data lives at
   https://www.sec.gov/Archives/edgar/data/<cik>/<accession-no-dashes>/primary_doc.xml
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .net import sec_get

INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{ymd}.idx"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"

# Form D industry groups that are not operating companies buying software/services.
EXCLUDED_INDUSTRIES = {
    "pooled investment fund", "commercial banking", "insurance", "investing", "investment banking",
    "reits and finance", "residential", "commercial", "other real estate", "construction",
    "lodging and conventions", "oil and gas", "coal mining", "electric utilities", "other energy",
    "agriculture", "airlines and airports", "tourism and travel services",
}
FUND_NAME_RE = re.compile(
    r"\b(fund|funds|lp|l\.p\.|partners|capital|holdings|spv|series [a-z0-9]+|feeder|master|trust|"
    r"properties|realty|apartments|reit|ventures|investors|opportunity|offshore|co-invest)\b", re.I)

INDEX_ROW = re.compile(r"^(?P<form>\S+(?:/A)?)\s{2,}(?P<company>.+?)\s{2,}(?P<cik>\d{1,10})\s{2,}"
                       r"(?P<date>\d{8}|\d{4}-\d{2}-\d{2})\s{2,}(?P<file>\S+)\s*$")


def index_url(d: date):
    return INDEX_URL.format(y=d.year, q=(d.month - 1) // 3 + 1, ymd=d.strftime("%Y%m%d"))


def parse_index(text):
    """Return new Form D filings (not amendments) from a daily form.idx."""
    out = []
    for line in text.splitlines():
        m = INDEX_ROW.match(line)
        if not m or m.group("form") != "D":
            continue
        f = m.group("file")  # edgar/data/1234567/0001234567-26-000001.txt
        acc = f.rsplit("/", 1)[-1].replace(".txt", "")
        d = m.group("date")
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
        out.append({"company": m.group("company").strip(), "cik": m.group("cik").lstrip("0"),
                    "accession": acc, "filed": d})
    return out


def _t(el, path):
    x = el.find(path) if el is not None else None
    return (x.text or "").strip() if x is not None and x.text else ""


def _children(el, path):
    x = el.find(path) if el is not None else None
    return list(x) if x is not None else []


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None  # "Indefinite" or blank


def parse_primary_doc(xml_text):
    root = ET.fromstring(xml_text)
    for el in root.iter():  # drop namespaces if present
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    iss = root.find("primaryIssuer")
    od = root.find("offeringData")
    people = []
    for p in root.findall("relatedPersonsList/relatedPersonInfo"):
        name = " ".join(x for x in [_t(p, "relatedPersonName/firstName"), _t(p, "relatedPersonName/lastName")] if x)
        rels = [r.text.strip() for r in p.findall("relatedPersonRelationshipList/relationship") if r.text]
        clar = _t(p, "relationshipClarification")
        people.append({"name": name, "relationships": rels, "title": clar})
    first_sale = _t(od, "typeOfFiling/dateOfFirstSale/value")
    return {
        "entity_name": _t(iss, "entityName"),
        "city": _t(iss, "issuerAddress/city"),
        "state": _t(iss, "issuerAddress/stateOrCountry"),
        "year_of_inc": _t(iss, "yearOfInc/value"),
        "entity_type": _t(iss, "entityType"),
        "industry": _t(od, "industryGroup/industryGroupType"),
        "revenue_range": _t(od, "issuerSize/revenueRange"),
        "is_amendment": _t(od, "typeOfFiling/newOrAmendment/isAmendment").lower() == "true",
        "first_sale": first_sale if re.match(r"\d{4}-\d{2}-\d{2}", first_sale) else "",
        "offering_total": _num(_t(od, "offeringSalesAmounts/totalOfferingAmount")),
        "amount_sold": _num(_t(od, "offeringSalesAmounts/totalAmountSold")),
        "securities": [x.tag for x in _children(od, "typesOfSecuritiesOffered")
                       if (x.text or "").strip().lower() == "true"],
        "people": people,
    }


def is_operating_company(filing_name, doc, min_amount=1_000_000):
    """Keep venture-style operating companies; drop funds, real estate, tiny raises."""
    if doc["is_amendment"]:
        return False, "amendment"
    if doc["industry"].lower() in EXCLUDED_INDUSTRIES:
        return False, f"industry: {doc['industry']}"
    if FUND_NAME_RE.search(doc["entity_name"] or filing_name):
        return False, "fund-like name"
    amt = max(doc["amount_sold"] or 0, doc["offering_total"] or 0)
    if amt < min_amount:
        return False, "raise under $1M or undisclosed"
    if doc["state"] and not re.fullmatch(r"[A-Z]{2}", doc["state"]):
        return False, f"non-US address: {doc['state']}"
    return True, ""


def stage_from_amount(amount):
    """Rough stage label from raise size. Approximate, shown as such in the UI."""
    if not amount:
        return ""
    if amount < 5e6:
        return "Seed"
    if amount < 20e6:
        return "Series A"
    if amount < 60e6:
        return "Series B"
    return "Series C+"


def collect(store, days=7, end=None, limit=400, log=print):
    """Pull Form D filings for the last `days` business days into the store."""
    end = end or date.today()
    filings = []
    d = end
    checked = 0
    while checked < days:
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        checked += 1
        status, text = sec_get(index_url(d))
        if status != 200:
            log(f"  index {d}: HTTP {status}")
            continue
        rows = parse_index(text)
        log(f"  index {d}: {len(rows)} Form D filings")
        filings.extend(rows)

    kept = new = 0
    for f in filings[:limit * 3]:
        if kept >= limit:
            break
        if FUND_NAME_RE.search(f["company"]):
            continue  # skip obvious funds before spending a request
        acc = f["accession"].replace("-", "")
        status, xml_text = sec_get(DOC_URL.format(cik=f["cik"], acc=acc))
        if status != 200:
            continue
        try:
            doc = parse_primary_doc(xml_text)
        except ET.ParseError:
            continue
        ok, _why = is_operating_company(f["company"], doc)
        if not ok:
            continue
        kept += 1
        amount = max(doc["amount_sold"] or 0, doc["offering_total"] or 0)
        name = doc["entity_name"] or f["company"]
        c = store.upsert_company(
            name, legal_name=name, cik=f["cik"], city=doc["city"].title(), state=doc["state"],
            industry=doc["industry"], year_of_inc=doc["year_of_inc"], revenue_range=doc["revenue_range"],
            stage_est=stage_from_amount(amount), source="formd")
        execs = [p["name"] for p in doc["people"] if "Executive Officer" in p["relationships"]][:6]
        sold, target = doc["amount_sold"] or 0, doc["offering_total"] or 0
        if sold and target and target > sold:
            title = f"Raised ${sold / 1e6:,.1f}M of a ${target / 1e6:,.1f}M round (Form D)"
        elif sold:
            title = f"Raised ${sold / 1e6:,.1f}M (Form D)"
        else:
            title = f"Raising up to ${target / 1e6:,.1f}M (Form D)"
        _sig, is_new = store.add_signal(
            c["id"], "raise", f["accession"], doc["first_sale"] or f["filed"], title,
            FILING_URL.format(cik=f["cik"], acc=acc),
            detail=f"Filed {f['filed']}; first sale {doc['first_sale'] or 'n/a'}; securities: {', '.join(doc['securities']) or 'n/a'}",
            data={"amount": amount, "amount_sold": doc["amount_sold"], "offering_total": doc["offering_total"],
                  "filed": f["filed"], "first_sale": doc["first_sale"], "executives": execs})
        new += is_new
    log(f"Form D: {len(filings)} filings scanned, {kept} operating companies kept, {new} new raise signals")
    return kept
