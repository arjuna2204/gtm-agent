# Pipeline Scout

An AI agent that finds companies that need a product **this week**, shows why with sourced signals, and drafts the outreach.

Built by Arjun Agarwal as a demo of how I'd build pipeline in a GTM role. Live at iamarjunagarwal.com/gtm (coming soon).

## How it works

| Stage | What it does | Runs |
| --- | --- | --- |
| Collect | Pulls fresh signals from free public sources into `data/` | Daily (GitHub Action) |
| Score | Code applies a 100-point rubric: fit, timing, signal strength | Weekly |
| Write | Claude drafts "why now", the persona, a brief and 3 emails for the top 100, citing signal IDs | Weekly |
| Check | Any claim without a valid signal ID is dropped | Weekly |
| Show | The site reads saved results; nothing is ever sent | Always |

### Signals (all free and public)

- **Raises:** SEC Form D filings (EDGAR daily index + each filing's `primary_doc.xml`). Funds, real estate and raises under $1M are filtered out.
- **Finance hiring:** Greenhouse, Lever and Ashby public job boards. Controller, FP&A, AP and head-of-finance roles count as "building the finance stack".
- **New finance leaders:** news RSS headlines announcing a CFO or VP Finance (confirmed by Claude before scoring).

No LinkedIn scraping, no paid databases, and no personal emails or phone numbers.

## Run it

Python 3.12, standard library only.

```bash
python -m unittest discover -s tests          # tests use saved sample data
SEC_USER_AGENT="Pipeline Scout you@example.com" python -m scout.collect all --days 5
```

`SEC_USER_AGENT` is required by the SEC's fair-access policy. In GitHub, set it as a repository **secret** so it stays masked in public logs.

## Data

- `data/companies.json`: one record per company (name, location, industry, job board, approximate size and stage)
- `data/signals.json`: one record per signal (type, date, title, source URL)
- `data/stats.json`: counts from the last run

Size and stage are estimates (from open roles and raise size) and are labelled as such.
