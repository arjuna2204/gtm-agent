"""Claude steps: confirm news signals (Haiku) and write account briefs + emails (Sonnet).

Trust rules, enforced in code:
- Claude only sees the signals stored for that account, each with an id.
- Every "why now" bullet and every email must cite signal ids; anything citing an unknown id is dropped.
- The prompt forbids facts not present in the inputs (revenue, headcount, customers).
- Nothing is ever sent; emails are drafts shown on the site.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from .store import DATA, now_iso

API = "https://api.anthropic.com/v1/messages"
FAST = os.environ.get("SCOUT_FAST_MODEL", "claude-haiku-5-5")
WRITER = os.environ.get("SCOUT_WRITER_MODEL", "claude-sonnet-5-5")
BANNED = ["i hope this finds you well", "i hope this email finds you", "touch base", "circle back", "synergy",
          "just checking in", "quick question"]


class ClaudeError(Exception):
    pass


def call_claude(model, system, user, max_tokens=1500, usage_log=None):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ClaudeError("ANTHROPIC_API_KEY is not set")
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 529) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise ClaudeError(f"HTTP {e.code}: {e.read()[:300]!r}")
    if usage_log is not None:
        u = out.get("usage", {})
        usage_log.append({"model": model, "in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0)})
    return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


# ------------------------------------------------------------ leader confirmation (Haiku)

LEADER_SYSTEM = ("You check news headlines for a sales research tool. Answer only with JSON. "
                 "Say true only if the headline clearly announces that THIS company hired, appointed or promoted "
                 "a CFO, VP Finance, Head of Finance or Controller. Same-name different companies, investors, "
                 "board seats at other firms, and departures are false.")


def confirm_leaders(store, usage, log=print):
    todo = [s for s in store.signals.values() if s["type"] == "leader" and s["data"].get("needs_check")]
    for s in todo:
        c = store.companies.get(s["company_id"], {})
        user = (f"Company: {c.get('name')} (location: {c.get('city') or ''} {c.get('state') or ''}, "
                f"industry: {c.get('industry') or 'unknown'})\nHeadline: {s['title']}\n"
                'Return {"confirmed": true|false, "person": "name or empty", "role": "title or empty"}')
        try:
            ans = extract_json(call_claude(FAST, LEADER_SYSTEM, user, 200, usage))
        except (ClaudeError, ValueError) as e:
            log(f"  leader check failed for {s['id']}: {e}")
            continue
        s["data"].update({"confirmed": bool(ans.get("confirmed")), "person": ans.get("person", ""),
                          "role": ans.get("role", ""), "needs_check": False})
    log(f"Leader checks: {len(todo)} headlines checked")


# ------------------------------------------------------------------ write-ups (Sonnet)

WRITER_SYSTEM = """You are a sharp B2B sales researcher writing for an account executive.
You will get ONE account, the product being sold, and a list of SIGNALS, each with an id.
Hard rules:
- Use ONLY facts in the inputs. Never state revenue, headcount, customers, funding investors or anything else not given.
- Every why_now bullet and every email must list the signal ids it relies on, copied exactly.
- Size and stage are estimates; if you mention them, say "about" or "roughly".
- Emails: plain text, <= 90 words, one specific signal per email, a clear low-effort ask, no flattery,
  no "I hope this finds you well", no fake familiarity, no em dashes. Sign as "[Your name]".
- Persona: a job title, never a person's name (even if one appears in the signals).
Return ONLY JSON in exactly this shape:
{"why_now":[{"text":"...","signal_ids":["..."]}],
 "persona":{"title":"...","why":"..."},
 "brief":"3 sentences: what they likely do (hedge if unsure), the likely spend pain now, the talk track.",
 "emails":[{"step":1,"subject":"...","body":"...","signal_ids":["..."]},
           {"step":2,"subject":"...","body":"...","signal_ids":["..."]},
           {"step":3,"subject":"...","body":"...","signal_ids":["..."]}]}"""


def account_prompt(c, sigs, score, profile):
    p = profile["product"]
    facts = {k: c.get(k) for k in ("name", "city", "state", "industry", "size_est", "stage_est", "open_roles",
                                   "locations_sample", "board_url") if c.get(k)}
    sig_list = [{"id": s["id"], "type": s["type"], "date": s["date"], "title": s["title"], "detail": s["detail"]}
                for s in sigs]
    return (f"PRODUCT: {p['name']}: {p['one_liner']}\nTypical buyers: {', '.join(p['buyer_titles'])}\n"
            f"Pains it solves: {'; '.join(p['pains'])}\n\nACCOUNT FACTS: {json.dumps(facts)}\n"
            f"SCORE: {score['total']}/100; reasons: {json.dumps(score['reasons'])}\n\n"
            f"SIGNALS: {json.dumps(sig_list)}")


def check_citations(draft, valid_ids):
    """Drop anything that cites no signal or an unknown one. Returns (clean, n_dropped)."""
    dropped = 0
    why = []
    for b in draft.get("why_now", []):
        ids = [i for i in b.get("signal_ids", []) if i in valid_ids]
        if ids and len(ids) == len(b.get("signal_ids", [])):
            why.append({"text": b["text"].strip(), "signal_ids": ids})
        else:
            dropped += 1
    emails = []
    for e in draft.get("emails", []):
        ids = e.get("signal_ids", [])
        body = (e.get("body") or "").strip()
        bad = not ids or any(i not in valid_ids for i in ids) or any(b in body.lower() for b in BANNED)
        if bad or len(body.split()) > 110:
            dropped += 1
            continue
        emails.append({"step": e.get("step"), "subject": (e.get("subject") or "").strip(), "body": body,
                       "signal_ids": ids})
    persona = draft.get("persona") or {}
    clean = {"why_now": why, "persona": {"title": persona.get("title", ""), "why": persona.get("why", "")},
             "brief": (draft.get("brief") or "").strip(), "emails": emails}
    return clean, dropped


def write_top(store, scores, profile, top=100, usage=None, log=print):
    path = DATA / "writeups.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    out, total_dropped, written = {}, 0, 0
    for row in scores[:top]:
        cid = row["company_id"]
        sigs = [store.signals[i] for i in row["signal_ids"] if i in store.signals]
        sig_key = ",".join(sorted(row["signal_ids"]))
        prev = existing.get(cid)
        if prev and prev.get("signal_key") == sig_key:
            out[cid] = prev  # nothing new: keep last week's write-up, save the API call
            continue
        c = store.companies[cid]
        try:
            raw = call_claude(WRITER, WRITER_SYSTEM, account_prompt(c, sigs, row, profile), 1800, usage)
            clean, dropped = check_citations(extract_json(raw), {s["id"] for s in sigs})
        except (ClaudeError, ValueError, json.JSONDecodeError) as e:
            log(f"  write-up failed for {cid}: {e}")
            if prev:
                out[cid] = prev
            continue
        total_dropped += dropped
        if not clean["why_now"] or not clean["emails"]:
            log(f"  {cid}: write-up rejected by citation check")
            continue
        out[cid] = dict(clean, company_id=cid, signal_key=sig_key, model=WRITER, written_at=now_iso(),
                        dropped_claims=dropped)
        written += 1
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    log(f"Write-ups: {written} new, {len(out)} total, {total_dropped} claims dropped by citation check")
    return out
