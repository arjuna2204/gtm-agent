// POST /api/gtm/writeup  { company_id, product, buyer }  ->  { writeup, remaining_today }
// Free write-ups on the site owner's Anthropic key, with hard limits:
// - company data and signals come from this deployment's own data file, never from the request
// - product text is length-clipped; only the product description reaches the model
// - per-visitor and global daily caps (in memory, best effort) + the Anthropic console spend limit as the hard stop
import fs from "fs";
import path from "path";
import { scoreCompany, buildPrompt, WRITER_SYSTEM, extractJson, checkCitations, validProduct, DEFAULT_BUYER, TEAM_LABELS, BANDS } from "../../site/gtm/assets/scout.js";

const MODEL = process.env.GTM_MODEL || "claude-sonnet-5-5";
const PER_VISITOR = Number(process.env.GTM_PER_VISITOR_DAILY || 5);
const GLOBAL = Number(process.env.GTM_GLOBAL_DAILY || 60);
const ALLOWED_ORIGINS = /^https:\/\/(www\.)?(gtm\.)?iamarjunagarwal\.com$|^http:\/\/localhost(:\d+)?$/;

let DATA = null;
function data() {
  if (!DATA) DATA = JSON.parse(fs.readFileSync(path.join(process.cwd(), "site/gtm/data/app.json"), "utf8"));
  return DATA;
}

let day = "", total = 0;
const perVisitor = new Map();
function take(visitor) {
  const today = new Date().toISOString().slice(0, 10);
  if (today !== day) { day = today; total = 0; perVisitor.clear(); }
  const used = perVisitor.get(visitor) || 0;
  if (used >= PER_VISITOR) return { ok: false, remaining: 0, error: `You've used today's ${PER_VISITOR} free write-ups. Add your own Anthropic API key to keep going, or come back tomorrow.` };
  if (total >= GLOBAL) return { ok: false, remaining: 0, error: "Today's free write-ups are used up across the site. Add your own Anthropic API key to keep going, or come back tomorrow." };
  perVisitor.set(visitor, used + 1); total++;
  return { ok: true, remaining: PER_VISITOR - used - 1 };
}
function refund(visitor) { perVisitor.set(visitor, Math.max(0, (perVisitor.get(visitor) || 1) - 1)); total = Math.max(0, total - 1); }

const str = (v, n) => String(v ?? "").slice(0, n).trim();
const strs = (v, n, each) => (Array.isArray(v) ? v : []).slice(0, n).map(x => str(x, each)).filter(Boolean);

function cleanProduct(p = {}) {
  return { name: str(p.name, 120), one_liner: str(p.one_liner, 400), buyer_titles: strs(p.buyer_titles, 6, 60),
    pains: strs(p.pains, 6, 120), teams: strs(p.teams, 10, 20).filter(t => t in TEAM_LABELS) };
}
function cleanBuyer(b = {}) {
  return { sizes: strs(b.sizes, 4, 10).filter(x => BANDS.includes(x)), states: strs(b.states, 20, 2).filter(x => /^[A-Z]{2}$/.test(x)),
    industries: strs(b.industries, 3, 60), window_days: [30, 90, 180, 365].includes(Number(b.window_days)) ? Number(b.window_days) : DEFAULT_BUYER.window_days,
    require_hiring: Boolean(b.require_hiring) };
}

async function callClaude(prompt) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": process.env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model: MODEL, max_tokens: 2000, system: WRITER_SYSTEM, messages: [{ role: "user", content: prompt }] }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(r.status === 429 || r.status === 529 ? "The writer is busy right now. Try again in a minute." : "The free writer is unavailable right now. You can use your own Anthropic API key instead.");
    err.status = 503; err.detail = j?.error?.message; throw err;
  }
  return (j.content || []).map(b => b.text || "").join("");
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") return res.status(405).json({ error: "Use POST." });
  const origin = req.headers.origin;
  if (origin && !ALLOWED_ORIGINS.test(origin)) return res.status(403).json({ error: "Not allowed from this site." });
  if (!process.env.ANTHROPIC_API_KEY) return res.status(503).json({ error: "Free write-ups aren't switched on yet. Use your own Anthropic API key for now." });

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
  const product = cleanProduct(body.product), buyer = cleanBuyer(body.buyer);
  if (!validProduct(product)) return res.status(400).json({ error: "Describe your product and pick at least one buying team first." });
  const company = data().companies.find(c => c.id === str(body.company_id, 120));
  if (!company) return res.status(404).json({ error: "Unknown company." });
  const score = scoreCompany(company, product, buyer);
  if (!score.signal_ids.length) return res.status(422).json({ error: "This company has no buying signals for your product, so there's nothing to cite." });

  const visitor = String(req.headers["x-forwarded-for"] || req.headers["x-real-ip"] || "unknown").split(",")[0].trim();
  const quota = take(visitor);
  if (!quota.ok) return res.status(429).json({ error: quota.error, remaining_today: 0 });

  try {
    let prompt = buildPrompt(company, score, product), clean = null;
    for (let attempt = 0; attempt < 3 && !clean; attempt++) {
      const raw = await callClaude(prompt);
      try { clean = checkCitations(extractJson(raw), score.signal_ids).clean; }
      catch { prompt = buildPrompt(company, score, product) + "\n\nIMPORTANT: your previous answer was not valid JSON. Return ONLY the JSON object, with any double quotes inside strings escaped."; }
    }
    if (!clean || !clean.why_now.length || !clean.emails.length) { refund(visitor); return res.status(502).json({ error: "The draft didn't pass the source check. Try again.", remaining_today: quota.remaining + 1 }); }
    return res.status(200).json({ writeup: clean, remaining_today: quota.remaining });
  } catch (e) {
    refund(visitor);
    console.error("writeup failed", e.detail || e.message);
    return res.status(e.status || 500).json({ error: e.message || "Something went wrong.", remaining_today: quota.remaining + 1 });
  }
}
