"""Tiny JSON store: data/companies.json and data/signals.json, committed to git by the Action.

companies: {company_id: {...}}
signals:   {signal_id: {company_id, type, date, title, detail, source_url, data, first_seen}}
Signal ids are content hashes, so re-collecting the same fact never duplicates it.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPANIES = DATA / "companies.json"
SIGNALS = DATA / "signals.json"

SIGNAL_TYPES = {"raise", "hiring", "leader"}


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today():
    return datetime.now(timezone.utc).date().isoformat()


LEGAL_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|llc|l\.l\.c|ltd|limited|co|corp|corporation|company|pbc|plc|lp|l\.p)\.?$", re.I)


def clean_name(name):
    n = (name or "").strip()
    for _ in range(3):
        n2 = LEGAL_SUFFIX.sub("", n).strip().rstrip(",")
        if n2 == n:
            break
        n = n2
    return n


def company_id(name):
    words = re.findall(r"[a-z0-9]+", clean_name(name).lower())
    return "-".join(words) or "unknown"


def signal_id(company, typ, key):
    return hashlib.sha1(f"{company}|{typ}|{key}".encode()).hexdigest()[:16]


class Store:
    def __init__(self, data_dir=DATA):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.companies = self._load(self.dir / "companies.json")
        self.signals = self._load(self.dir / "signals.json")

    @staticmethod
    def _load(p):
        if p.exists():
            return json.loads(p.read_text() or "{}")
        return {}

    def save(self):
        for name, obj in (("companies.json", self.companies), ("signals.json", self.signals)):
            (self.dir / name).write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n")

    def upsert_company(self, name, **fields):
        cid = company_id(name)
        c = self.companies.get(cid)
        if c is None:
            c = {"id": cid, "name": clean_name(name), "first_seen": now_iso(), "sources": []}
            self.companies[cid] = c
        for k, v in fields.items():
            if k == "source":
                if v and v not in c["sources"]:
                    c["sources"].append(v)
            elif v not in (None, "", [], {}):
                c[k] = v
        c["updated"] = now_iso()
        return c

    def add_signal(self, cid, typ, key, date, title, source_url, detail="", data=None):
        assert typ in SIGNAL_TYPES, typ
        sid = signal_id(cid, typ, key)
        existing = self.signals.get(sid)
        sig = {"id": sid, "company_id": cid, "type": typ, "date": date, "title": title,
               "detail": detail, "source_url": source_url, "data": data or {},
               "first_seen": existing["first_seen"] if existing else now_iso(), "last_seen": now_iso()}
        self.signals[sid] = sig
        return sig, existing is None

    def signals_for(self, cid, typ=None):
        return [s for s in self.signals.values() if s["company_id"] == cid and (typ is None or s["type"] == typ)]
