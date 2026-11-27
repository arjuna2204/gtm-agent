"""HTTP helpers (stdlib only). Adapted from job-agent/finder.py."""
import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

# SEC asks automated clients to identify themselves with a contact. Set SEC_USER_AGENT
# (e.g. "Pipeline Scout yourname@example.com") as a repo variable; never hard-code it.
SEC_UA = os.environ.get("SEC_USER_AGENT", "PipelineScout research (contact not set)")
WEB_UA = "Mozilla/5.0 (compatible; PipelineScout/1.0; portfolio research)"


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def http_get(url, headers=None, timeout=20, retries=2, ua=WEB_UA, max_bytes=5_000_000):
    """Return (status, text). status 0 = network error."""
    hdrs = {"User-Agent": ua, "Accept-Encoding": "identity"}
    hdrs.update(headers or {})
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.status, r.read(max_bytes).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, ""
        except Exception:
            if attempt < retries:
                time.sleep(1.5)
                continue
            return 0, ""
    return 0, ""


def http_get_json(url, **kw):
    status, body = http_get(url, headers={"Accept": "application/json"}, **kw)
    try:
        return status, json.loads(body) if body else None
    except json.JSONDecodeError:
        return status, None


_last_sec = [0.0]


def sec_get(url):
    """SEC fair-access: <=10 requests/second with a declared User-Agent."""
    wait = 0.12 - (time.time() - _last_sec[0])
    if wait > 0:
        time.sleep(wait)
    _last_sec[0] = time.time()
    return http_get(url, ua=SEC_UA, headers={"Accept": "*/*"})


TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(s):
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()
