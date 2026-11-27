// Pipeline Scout shared logic: scoring, prompt, citation check.
// Used by the web app (browser) and the write-up API (Node). Keep it dependency-free.

export const TEAM_LABELS = {
  finance: "Finance", sales: "Sales", marketing: "Marketing", engineering: "Engineering", data: "Data",
  security_it: "Security & IT", people: "People & HR", customer: "Customer success", operations: "Operations", legal: "Legal",
};

export const BANDS = ["under 50", "50-200", "200-500", "500+"];
const STAGE_TO_BAND = { "Seed": "under 50", "Series A": "50-200", "Series B": "50-200", "Series C+": "200-500" };
const US_STATES = new Set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(" "));
const US_LOC = new RegExp("\\b(united states|usa|u\\.s\\.|remote[ -]?(us|usa)|new york|san francisco|los angeles|chicago|boston|austin|seattle|miami|denver|atlanta|washington,? dc|nyc|sf bay)\\b|, (" + [...US_STATES].join("|") + ")\\b", "i");

export const PRESETS = {
  spend: { label: "Spend management", name: "a corporate card and spend management platform",
    one_liner: "Corporate cards, expense management, bill pay and accounting automation in one place, so finance teams close faster and control spend.",
    buyer_titles: ["CFO", "VP Finance", "Head of Finance", "Controller"], teams: ["finance"],
    pains: ["expense reports and receipt chasing", "manual AP and bill pay", "slow month-end close", "no real-time view of spend"] },
  payroll: { label: "Payroll & HR", name: "a payroll, benefits and HR platform",
    one_liner: "Payroll, benefits, onboarding and HR records in one system that scales with headcount.",
    buyer_titles: ["Head of People", "VP People", "HR Director", "CFO"], teams: ["people", "finance"],
    pains: ["payroll run by hand or across tools", "onboarding that breaks as hiring speeds up", "benefits admin", "compliance across states"] },
  sales: { label: "Sales engagement", name: "a sales engagement and pipeline platform",
    one_liner: "Prospecting, sequences, call recording and pipeline analytics so a growing sales team ramps faster.",
    buyer_titles: ["VP Sales", "Head of Sales", "Revenue Operations Lead", "CRO"], teams: ["sales"],
    pains: ["slow rep ramp", "inconsistent outreach", "no visibility into pipeline quality", "CRM hygiene"] },
  devtools: { label: "Developer tools", name: "a developer platform for building and running software",
    one_liner: "Infrastructure, CI/CD and observability tools that let a growing engineering team ship faster with fewer incidents.",
    buyer_titles: ["VP Engineering", "Head of Platform", "Engineering Manager", "CTO"], teams: ["engineering", "data"],
    pains: ["slow builds and deploys", "on-call load as the team grows", "cloud cost creep", "fragmented tooling"] },
  security: { label: "Security & compliance", name: "a security and compliance automation platform",
    one_liner: "Automates SOC 2 and ISO evidence collection, device management and access reviews.",
    buyer_titles: ["Head of Security", "CISO", "IT Manager", "CTO"], teams: ["security_it", "engineering"],
    pains: ["first SOC 2 audit", "manual access reviews", "device and identity sprawl", "security questionnaires slowing deals"] },
  recruiting: { label: "Recruiting software", name: "an applicant tracking and recruiting platform",
    one_liner: "Sourcing, interview scheduling and hiring analytics for teams scaling headcount quickly.",
    buyer_titles: ["Head of Talent", "Recruiting Lead", "Head of People"], teams: ["people"],
    pains: ["hiring plans outgrowing spreadsheets", "slow interview scheduling", "no hiring funnel data"] },
  custom: { label: "Custom product", name: "", one_liner: "", buyer_titles: [], teams: [], pains: [] },
};

export const DEFAULT_BUYER = { sizes: ["50-200", "200-500"], states: [], industries: [], window_days: 180, require_hiring: false };

const daysSince = (iso, today) => {
  if (!iso) return null;
  const d = Date.parse(iso.slice(0, 10) + "T12:00:00Z");
  return isNaN(d) ? null : Math.round((today - d) / 864e5);
};

export function sizeOf(c) {
  if (c.size_est) return { band: c.size_est, how: "estimated from open roles" };
  if (c.stage_est && STAGE_TO_BAND[c.stage_est]) return { band: STAGE_TO_BAND[c.stage_est], how: "estimated from raise size" };
  return { band: "", how: "" };
}

export function isUS(c) {
  return US_STATES.has(c.state) || US_LOC.test((c.locations || []).join(" | "));
}

export function scoreCompany(c, product, buyer, today = Date.now()) {
  const parts = {}, reasons = {}, used = [];
  const teams = new Set(product.teams || []);

  if (!buyer.industries.length) { parts.industry = 15; reasons.industry = "Any industry"; }
  else if (c.industry && buyer.industries.includes(c.industry)) { parts.industry = 15; reasons.industry = `${c.industry} is a target industry`; }
  else if (!c.industry) { parts.industry = 8; reasons.industry = "Industry unknown: partial credit"; }
  else { parts.industry = 0; reasons.industry = `${c.industry} is outside the target industries`; }

  const { band, how } = sizeOf(c);
  if (!buyer.sizes.length || (band && buyer.sizes.includes(band))) {
    parts.size = band || !buyer.sizes.length ? 15 : 0;
    reasons.size = band ? `About ${band} people (${how})` : "Any size";
  } else if (band && buyer.sizes.some(b => Math.abs(BANDS.indexOf(b) - BANDS.indexOf(band)) === 1)) {
    parts.size = 8; reasons.size = `About ${band} people, next to the target range (${how})`;
  } else { parts.size = 0; reasons.size = band ? `About ${band} people, outside the range (${how})` : "Size unknown"; }

  const us = isUS(c);
  const inStates = !buyer.states.length || buyer.states.includes(c.state);
  parts.region = us && inStates ? 10 : 0;
  reasons.region = !us ? "No US location found" : inStates ? (buyer.states.length ? `In ${c.state}` : "US-based") : "Outside the chosen states";

  parts.raise = 0; reasons.raise = "No raise in the funding window";
  const raises = c.signals.filter(s => s.type === "raise").sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  if (raises.length) {
    const r = raises[0], d = daysSince(r.date, today);
    if (d !== null && d <= buyer.window_days) {
      parts.raise = d < 30 ? 20 : d <= 90 ? 14 : 6;
      reasons.raise = `${r.title.replace(/ \(Form D\)/, "")}, ${d} days ago`;
      used.push(r.id);
    }
  }

  const hires = c.signals.filter(s => s.type === "hiring" && teams.has(s.team));
  const key = hires.filter(s => s.key);
  const pick = (key.length ? key : hires).slice(0, 3);
  parts.hiring = key.length ? 15 : hires.length ? 8 : 0;
  reasons.hiring = pick.length ? "Hiring " + pick.map(s => s.title.replace(/^Hiring: /, "")).join(", ")
    : `No open roles on the buying team${teams.size ? "" : " (choose a buying team)"}`;
  used.push(...pick.map(s => s.id));

  const leader = teams.has("finance") ? c.signals.find(s => s.type === "leader" && (daysSince(s.date, today) ?? 999) <= 120) : null;
  parts.leader = leader ? 10 : 0;
  reasons.leader = leader ? leader.title : teams.has("finance") ? "No new finance leader found" : "Leader news tracked for finance buyers only";
  if (leader) used.push(leader.id);

  const types = ["raise", "hiring", "leader"].filter(k => parts[k] > 0).length;
  parts.strength = 5 * types;
  reasons.strength = `${types} independent signal type(s)`;
  const total = Object.values(parts).reduce((a, b) => a + b, 0);
  const timing = parts.raise + parts.hiring + parts.leader;
  return { total, timing, parts, reasons, signal_ids: used, qualifies: timing > 0 && (!buyer.require_hiring || parts.hiring > 0) };
}

export function rankAll(companies, product, buyer, today = Date.now()) {
  const rows = [];
  for (const c of companies) {
    const s = scoreCompany(c, product, buyer, today);
    if (s.qualifies) rows.push({ c, s });
  }
  rows.sort((a, b) => b.s.total - a.s.total || b.s.timing - a.s.timing || a.c.id.localeCompare(b.c.id));
  rows.forEach((r, i) => { r.rank = i + 1; });
  return rows;
}

// ------------------------------------------------------------------ write-ups

export const WRITER_SYSTEM = `You are a sharp B2B sales researcher writing for an account executive.
You will get ONE account, the product being sold, and a list of SIGNALS, each with an id.
Hard rules:
- Use ONLY facts in the inputs. Never state revenue, headcount, customers, funding investors or anything else not given.
- Never invent product results or statistics (no "close 5 days faster", "save 20%"); describe benefits qualitatively.
- Every why_now bullet and every email must list the signal ids it relies on, copied exactly.
- Size and stage are estimates; if you mention them, say "about" or "roughly".
- Write dates like "Oct 16", never as 2026-10-16. Inside JSON strings, never use unescaped double quotes.
- Emails: plain text, <= 90 words, one specific signal per email, a clear low-effort ask, no flattery,
  no "I hope this finds you well", no fake familiarity, no em dashes. Sign as "[Your name]".
- Persona: a job title, never a person's name (even if one appears in the signals).
Return ONLY JSON in exactly this shape:
{"why_now":[{"text":"...","signal_ids":["..."]}],
 "persona":{"title":"...","why":"..."},
 "brief":"3 sentences: what they likely do (hedge if unsure), the likely pain now, the talk track.",
 "emails":[{"step":1,"subject":"...","body":"...","signal_ids":["..."]},
           {"step":2,"subject":"...","body":"...","signal_ids":["..."]},
           {"step":3,"subject":"...","body":"...","signal_ids":["..."]}]}`;

const BANNED = ["i hope this finds you well", "i hope this email finds you", "touch base", "circle back", "synergy", "just checking in", "quick question"];

export function buildPrompt(c, score, product) {
  const sigs = c.signals.filter(s => score.signal_ids.includes(s.id));
  const facts = {};
  for (const k of ["name", "city", "state", "industry", "stage_est", "open_roles", "locations", "board_url"]) if (c[k]) facts[k] = c[k];
  const { band, how } = sizeOf(c);
  if (band) facts.size_estimate = `about ${band} people (${how})`;
  const clip = (s, n) => String(s || "").slice(0, n);
  return `PRODUCT: ${clip(product.name, 120)}: ${clip(product.one_liner, 400)}
Typical buyers: ${(product.buyer_titles || []).map(t => clip(t, 60)).join(", ") || "not given"}
Pains it solves: ${(product.pains || []).map(t => clip(t, 120)).join("; ") || "not given"}

ACCOUNT FACTS: ${JSON.stringify(facts)}
SCORE: ${score.total}/100; reasons: ${JSON.stringify(score.reasons)}

SIGNALS: ${JSON.stringify(sigs.map(s => ({ id: s.id, type: s.type, date: s.date, title: s.title, detail: s.detail })))}`;
}

export function extractJson(text) {
  const m = String(text || "").match(/\{[\s\S]*\}/);
  if (!m) throw new Error("no JSON object in model output");
  return JSON.parse(m[0]);
}

export function checkCitations(draft, validIds) {
  const valid = new Set(validIds);
  let dropped = 0;
  const why = [];
  for (const b of draft.why_now || []) {
    const ids = b.signal_ids || [];
    if (ids.length && ids.every(i => valid.has(i))) why.push({ text: String(b.text || "").trim(), signal_ids: ids });
    else dropped++;
  }
  const emails = [];
  for (const e of draft.emails || []) {
    const ids = e.signal_ids || [], body = String(e.body || "").trim(), low = body.toLowerCase();
    if (!ids.length || !ids.every(i => valid.has(i)) || BANNED.some(b => low.includes(b)) || body.split(/\s+/).length > 110) { dropped++; continue; }
    emails.push({ step: e.step, subject: String(e.subject || "").trim(), body, signal_ids: ids });
  }
  const p = draft.persona || {};
  return { clean: { why_now: why, persona: { title: String(p.title || ""), why: String(p.why || "") }, brief: String(draft.brief || "").trim(), emails }, dropped };
}

export function validProduct(p) {
  return p && String(p.name || "").trim().length >= 3 && String(p.one_liner || "").trim().length >= 10 && (p.teams || []).length > 0;
}
