# AI-Powered Hyper-Personalized Job Outreach Automation

Production-grade AI outreach system for securing AI Engineer, Consultant, Internship, and contract roles through hyper-personalized cold outreach to 21,000+ digital agencies.

## Stack

- **Backend:** Python 3.11+, FastAPI
- **Database:** Supabase PostgreSQL
- **Email:** Brevo (3 accounts, 900 emails/day)
- **AI:** Gemini → Groq → OpenRouter → Cerebras → Mistral fallback chain
- **Scraping:** Playwright with 30-day cache
- **Dashboard:** Streamlit (6 pages)
- **Scheduler:** GitHub Actions cron (7 PM IST)
- **Hosting:** Render free tier

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
copy .env.example .env
# Fill in DATABASE_URL, API keys, Brevo credentials
```

### 3. Apply database migration

Run the SQL in `supabase/migrations/001_initial_schema.sql` against your Supabase project (via dashboard SQL editor or Supabase CLI).

### 4. Import leads

```bash
python scripts/import_csv.py
```

### 5. Run API locally

```bash
uvicorn src.api.main:app --reload --port 8000
```

### 6. Run dashboard locally

```bash
streamlit run streamlit_app/app.py
```

## Deploy to Render

1. Push repo to GitHub
2. Connect to Render and deploy using `render.yaml` Blueprint
3. Set all environment variables from `.env.example`
4. Register webhook URLs in Brevo (append `?secret=YOUR_WEBHOOK_SECRET` from Render env):
   - `https://your-app.onrender.com/webhooks/brevo/transactional?secret=...`
   - `https://your-app.onrender.com/webhooks/brevo/inbound?secret=...`
5. Copy `JOB_SECRET` from Render → GitHub secrets as `JOB_SECRET`; set `RENDER_URL` to your API URL

## Daily Workflow

GitHub Actions starts at **7:00 PM IST** and calls `/jobs/daily-outreach` every **10 minutes** until the daily job completes. Each call processes one **chunk** (~15 leads) synchronously — safe for Render free tier.

1. Follow-ups first (up to 450/day across 3 Brevo accounts)
2. New outreach by match score (up to 450/day)
3. Per lead: cached analysis → LLM email → Brevo send (validation must pass)

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Health check |
| POST | `/jobs/daily-outreach` | Bearer JOB_SECRET | Trigger daily pipeline |
| POST | `/jobs/resume/{job_id}` | Bearer JOB_SECRET | Resume failed job |
| GET | `/jobs/{job_id}/status` | Bearer JOB_SECRET | Job status |
| POST | `/webhooks/brevo/transactional` | None | Brevo event webhook |
| POST | `/webhooks/brevo/inbound` | None | Reply webhook |

## Project Structure

```
src/
  api/          FastAPI app + webhooks
  core/         Config, logging, retry
  db/           SQLAlchemy models
  services/     Business logic (scrape, LLM, Brevo, follow-ups)
  utils/        URL/email normalization
streamlit_app/  Dashboard (6 pages)
scripts/        CSV import
prompts/        LLM prompt templates
config/         Sender profile JSON
supabase/       Database migrations
```

## Tests

```bash
pytest tests/ -v
```
