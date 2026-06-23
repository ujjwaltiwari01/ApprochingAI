# AI-Powered Hyper-Personalized Job Outreach System

**Author:** Ujjwal Tiwari  
**Purpose:** Automate cold outreach to ~67,000 digital agency decision-makers to land AI Engineer, Consultant, Internship, and contract roles — at scale, with real personalization, not mail-merge spam.


- Repo: `https://github.com/ujjwaltiwari01/ApprochingAI`

---

## Table of Contents

1. [Start Here — Zero Prior Knowledge](#1-start-here--zero-prior-knowledge)
2. [The Business Problem](#2-the-business-problem)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Why Each Technology Was Chosen](#4-why-each-technology-was-chosen)
5. [System Components Deep Dive](#5-system-components-deep-dive)
6. [Database Schema & Data Model](#6-database-schema--data-model)
7. [Lead Lifecycle (State Machine)](#7-lead-lifecycle-state-machine)
8. [End-to-End Data Flow](#8-end-to-end-data-flow)
9. [Daily Outreach Pipeline](#9-daily-outreach-pipeline)
10. [Single Lead Processing (Micro Flow)](#10-single-lead-processing-micro-flow)
11. [Chunked Jobs — Why Not One Big Cron?](#11-chunked-jobs--why-not-one-big-cron)
12. [LLM Layer — Multi-Provider Fallback](#12-llm-layer--multi-provider-fallback)
13. [Email Generation & Validation Gate](#13-email-generation--validation-gate)
14. [Match Scoring & Lead Prioritization](#14-match-scoring--lead-prioritization)
15. [Dual Lead Datasets (21K + 50K USA)](#15-dual-lead-datasets-21k--50k-usa)
16. [Brevo Multi-Account Email Delivery](#16-brevo-multi-account-email-delivery)
17. [Webhooks & Engagement Tracking](#17-webhooks--engagement-tracking)
18. [Follow-Up Engine](#18-follow-up-engine)
19. [Deployment Architecture (Render)](#19-deployment-architecture-render)
20. [GitHub Actions Scheduler](#20-github-actions-scheduler)
21. [Streamlit Dashboard](#21-streamlit-dashboard)
22. [Security Model](#22-security-model)
23. [Project Structure (File by File)](#23-project-structure-file-by-file)
24. [Environment Variables](#24-environment-variables)
25. [Local Development Setup](#25-local-development-setup)
26. [API Reference](#26-api-reference)
27. [Interview Prep — Questions & Answers](#27-interview-prep--questions--answers)
28. [Troubleshooting Runbook](#28-troubleshooting-runbook)
29. [Tests](#29-tests)
30. [Future Improvements](#30-future-improvements)

---

## 1. Start Here — Zero Prior Knowledge

### What does this system do in one sentence?

It reads thousands of agency contacts from a database, researches each company, uses AI to write a unique job-seeking email, sends it through email APIs, tracks opens/clicks/replies, and sends intelligent follow-ups — automatically, every day.

### The analogy (explain in an interview)

Think of it as a **recruiting assistant factory**:

| Human recruiter | This system |
|-----------------|-------------|
| Excel sheet of companies | `leads` table in PostgreSQL |
| Google the company | `WebsiteAnalyzer` + `website_cache` |
| Write a personalized email | `EmailGenerator` + LLM |
| Send via Gmail | `BrevoClient` (3 accounts) |
| Track who opened/replied | Brevo webhooks → `email_events` |
| Follow up after 4 days | `FollowupEngine` |
| Daily to-do list | `JobRunner` + GitHub Actions cron |

### Scale today

| Metric | Value |
|--------|-------|
| Total leads in DB | ~67,500 |
| USA agency owners (high priority) | ~49,000 |
| Original agency list | ~18,500 |
| Max new emails/day | 450 (150 × 3 Brevo accounts) |
| Max follow-ups/day | 450 (150 × 3 accounts) |
| Chunk size per API call | 15 leads |
| LLM providers (fallback chain) | Mistral → Cerebras → OpenRouter → Gemini → Groq |

---

## 2. The Business Problem

### Problem

Ujjwal is an AI engineer seeking roles at digital agencies. Manually emailing 67,000 contacts is impossible. Generic templates get ignored (<5% open rates). Real personalization at scale requires automation.

### Constraints (real-world, not textbook)

1. **Budget:** Free tiers everywhere (Render, Brevo, LLM APIs, Supabase free tier).
2. **Time:** Render free tier kills long HTTP requests (~30s limit per request).
3. **Deliverability:** Brevo free = 300 emails/day/account; need 3 accounts for volume.
4. **Quality:** Emails must pass validation (word count, no buzzwords, agency-specific hook) or they don't send.
5. **Compliance:** Track bounces, stop on reply, `do_not_contact` flag.

### Success metrics

- Open rate target: 50–70% (based on prior Converzia outreach data in sender profile).
- Reply / interview conversion tracked via `lead_status` funnel.
- Zero duplicate sends (unique email index).
- Resumable jobs if server crashes mid-batch.

---

## 3. High-Level Architecture

```mermaid
flowchart TB
    subgraph DataSources["Data Sources"]
        CSV1["21K Agency CSV"]
        CSV2["50K USA Owners CSV"]
    end

    subgraph Storage["Supabase PostgreSQL"]
        Leads[(leads)]
        Cache[(website_cache)]
        Jobs[(jobs)]
        Events[(email_events)]
        Content[(generated_content)]
        Counters[(daily_send_counters)]
    end

    subgraph Scheduler["Scheduler"]
        GHA["GitHub Actions<br/>7 PM + 1 AM IST"]
    end

    subgraph API["Render: outreach-api"]
        FastAPI["FastAPI"]
        JR["JobRunner"]
        BP["BatchProcessor"]
        WA["WebsiteAnalyzer"]
        EG["EmailGenerator"]
        LLM["LLMClient"]
        BC["BrevoClient"]
        FE["FollowupEngine"]
    end

    subgraph External["External Services"]
        Brevo["Brevo API × 3"]
        LLMProviders["Mistral / Cerebras / Groq / Gemini / OpenRouter"]
        Playwright["Playwright<br/>(optional scrape)"]
    end

    subgraph UI["Render: outreach-dashboard"]
        Streamlit["Streamlit Dashboard"]
    end

    CSV1 --> Leads
    CSV2 --> Leads
    GHA -->|"POST /jobs/daily-outreach"| FastAPI
    FastAPI --> JR
    JR --> BP
    BP --> WA
    BP --> EG
    BP --> BC
    BP --> FE
    WA --> Cache
    WA --> Playwright
    EG --> LLM
    LLM --> LLMProviders
    BC --> Brevo
    Brevo -->|"webhooks"| FastAPI
    Streamlit -->|"Supabase REST"| Storage
    JR --> Jobs
    BP --> Leads
    BP --> Content
    FastAPI --> Events
```

### Request path (simplified)

```
GitHub Actions cron
    → POST /jobs/daily-outreach (Bearer JOB_SECRET)
        → JobRunner.run_daily_outreach_chunk()
            → FollowupEngine (pick due follow-ups)
            → BatchProcessor.process_followups()
            → BatchProcessor.process_new_leads()
                → WebsiteAnalyzer.analyze_for_lead()
                → EmailGenerator.generate_initial_email()
                → BrevoClient.send_email()
                → Update lead status in DB
            → Save checkpoint to jobs table
        → Return { completed: true/false }
    → Sleep 5 minutes
    → Repeat until completed or 6h timeout
```

---

## 4. Why Each Technology Was Chosen

*Interview tip: Always state the constraint first, then the choice, then the trade-off.*

### Python 3.11 + FastAPI (API layer)

| Why chosen | Trade-off |
|------------|-----------|
| Async-native (`async/await`) for I/O-bound work (DB, HTTP, LLM) | Not ideal for CPU-heavy scraping at scale |
| FastAPI auto-generates OpenAPI docs, type hints, dependency injection | Smaller ecosystem than Django for admin UIs |
| Single process handles webhooks + job triggers | Need external scheduler (GitHub Actions) for cron |

**Interview answer:** *"I chose FastAPI because the workload is I/O-bound — waiting on LLM APIs, Brevo, and PostgreSQL. Async lets one Render instance handle concurrent operations without threading complexity."*

### Supabase PostgreSQL (database)

| Why chosen | Trade-off |
|------------|-----------|
| Managed Postgres with REST API (dashboard uses it without SQLAlchemy) | Free tier connection limits |
| JSONB for `csv_raw`, `checkpoint`, `analysis_json` — flexible schema for CSV variants | No built-in job queue |
| Session pooler fixes Render IPv6 issue (`SUPABASE_POOLER_HOST`) | Pooler adds latency vs direct connection |

**Interview answer:** *"I needed relational integrity for leads and events, plus JSONB for raw CSV rows. Supabase gives Postgres + a REST layer so the Streamlit dashboard doesn't need the async DB driver."*

### SQLAlchemy 2.0 + asyncpg (API DB access)

| Why chosen | Trade-off |
|------------|-----------|
| Type-safe ORM, async sessions, enum mapping | Heavier than raw SQL |
| Same models for API; dashboard bypasses via REST | Two data access patterns to maintain |

### Brevo (email, not SMTP)

| Why chosen | Trade-off |
|------------|-----------|
| Transactional API with webhooks (open, click, bounce, reply) | 300 emails/day free per account |
| `messageId` tracking links sends to webhook events | 3 accounts = operational overhead |
| API simpler than self-hosted SMTP + reputation management | Vendor lock-in |

**Interview answer:** *"SMTP would require warming IPs and building event tracking myself. Brevo's API + webhooks give delivery status in hours, not weeks of infra work."*

### Multi-LLM fallback chain

| Why chosen | Trade-off |
|------------|-----------|
| Free tiers have rate limits; one provider failing shouldn't stop the pipeline | Non-deterministic output across providers |
| Mistral first (fast, good prose); Groq last (strict daily quota) | Prompt must work across models |
| Per-provider cooldown after 429 errors | Complex client code (`llm_client.py`) |

### Playwright + website_cache

| Why chosen | Trade-off |
|------------|-----------|
| Real website text beats guessing from company name | Heavy Docker image, slow, blocked on Render free |
| **Production:** `SKIP_PLAYWRIGHT=true` — use CSV + pre-seeded cache | Less fresh data |
| 30-day TTL avoids re-scraping same domain | Stale cache if site redesigns |

**Interview answer:** *"Scraping is the quality ceiling but the cost floor on free hosting. I cache aggressively and seed cache from CSV at import time so 80%+ leads have analysis without Playwright."*

### GitHub Actions (scheduler, not Render Cron)

| Why chosen | Trade-off |
|------------|-----------|
| Render free tier has no reliable long-running cron | GitHub schedule can delay 1–4 hours |
| 6-hour job timeout fits chunked loop | Public repo required for free scheduled Actions |
| Decouples scheduling from API server | Another secret to manage (`JOB_SECRET`) |

### Streamlit (dashboard)

| Why chosen | Trade-off |
|------------|-----------|
| Ship a UI in hours, not days | Not production-grade multi-user app |
| Python-only — same team/language as backend | Separate deploy on Render |
| Pages for metrics, leads, preview, manual trigger | Uses Supabase REST, not shared ORM |

### Docker (API only)

| Why chosen | Trade-off |
|------------|-----------|
| Reproducible Python 3.11 environment on Render | Dashboard uses plain `pip install` (lighter) |
| Playwright deps available if needed locally | Larger build than native Python |

---

## 5. System Components Deep Dive

### 5.1 `src/api/main.py` — API Gateway

**Responsibilities:**
- Expose HTTP endpoints
- Protect job endpoints with `JOB_SECRET` Bearer token
- **Single-flight lock** (`asyncio.Lock`) — only one chunk runs at a time (prevents double-sends if GitHub Actions overlaps)

```python
# Why a lock?
# GitHub Actions might retry or overlap with manual trigger.
# Without lock, two chunks could pick the same NEW leads.
async with _job_lock:
    result = await runner.run_daily_outreach_chunk()
```

### 5.2 `src/services/job_runner.py` — Orchestrator

**Responsibilities:**
- Create or resume today's `DAILY_OUTREACH` job
- Process one **chunk** per HTTP request (default 15 leads)
- **Priority order:** follow-ups first, then new leads
- Persist **checkpoint** JSON between chunks

**Checkpoint structure (example):**
```json
{
  "followups_sent_count": 45,
  "followups_done": false,
  "new_sent_count": 120,
  "new_done": false,
  "followup_stats": { "sent": 45, "errors": 2 },
  "new_stats": { "sent": 118, "generated": 125 }
}
```

**Why follow-ups first?**  
Warm leads (already emailed once) convert better. Burning daily quota on new cold leads while follow-ups age out wastes prior investment.

### 5.3 `src/services/batch_processor.py` — Per-Lead Pipeline

For each lead in a chunk:

1. `WebsiteAnalyzer.analyze_for_lead()` → agency analysis dict
2. `EmailGenerator.generate_initial_email()` → subject + body + validation
3. If validation fails and `ALLOW_INVALID_SEND=false` → skip send, mark generated only
4. `BrevoClient.send_email()` → deliver
5. Update `leads.status`, `sent_at`, `message_id`, `brevo_account`

**Important design choice:** Brevo send success does **not** roll back if DB update fails. Email delivered > DB consistency. Logged for manual fix.

### 5.4 `src/services/website_analyzer.py` — Research Layer

**Resolution order:**
```
1. website_cache (if TTL < 30 days) → return analysis_json
2. SKIP_PLAYWRIGHT=true → agency_analysis_from_csv_raw(lead.csv_raw)
3. Else Playwright scrape /, /about, /services, /team → LLM summarize → cache
```

### 5.5 `src/services/email_generator.py` — Content Layer

- Loads `prompts/master_email.txt`, `prompts/subject_lines.txt`
- Injects `sender_profile.json`, agency analysis, recipient first name (USA leads)
- Runs **parallel** LLM calls: body + subject lines (`asyncio.gather`)
- **Validation gate** before send (word count, buzzwords, portfolio links, agency-specific tokens)
- Safe prompt formatting (`_format_prompt`) — won't crash on `{braces}` in examples

### 5.6 `src/services/llm_client.py` — Provider Abstraction

See [Section 12](#12-llm-layer--multi-provider-fallback).

### 5.7 `src/services/brevo_client.py` — Delivery Layer

See [Section 16](#16-brevo-multi-account-email-delivery).

### 5.8 `src/services/followup_engine.py` — Retention Layer

See [Section 18](#18-follow-up-engine).

### 5.9 `src/services/match_scorer.py` — Prioritization

See [Section 14](#14-match-scoring--lead-prioritization).

---

## 6. Database Schema & Data Model

```mermaid
erDiagram
    leads ||--o{ generated_content : has
    leads ||--o{ email_events : has
    leads {
        uuid id PK
        text email UK
        text company_name
        text name
        text website
        text country
        enum status
        int match_score
        int hiring_probability
        text lead_source
        jsonb csv_raw
        timestamptz sent_at
        timestamptz opened_at
        timestamptz replied_at
        int brevo_account
        text message_id
    }
    website_cache {
        uuid id PK
        text website UK
        text summary
        jsonb analysis_json
        timestamptz last_scraped
    }
    jobs {
        uuid id PK
        enum job_type
        enum status
        jsonb checkpoint
        jsonb error_log
    }
    email_events {
        uuid id PK
        uuid lead_id FK
        text event_type
        text brevo_event_id UK
    }
    daily_send_counters {
        date send_date
        int brevo_account
        int new_sent
        int followup_sent
    }
    generated_content {
        uuid id PK
        uuid lead_id FK
        text subject
        text email_body
        text llm_provider
        bool validation_passed
    }
```

### Table purposes (interview crib sheet)

| Table | Purpose |
|-------|---------|
| `leads` | Master contact record + funnel status |
| `website_cache` | Deduped research per domain (avoid re-scraping) |
| `generated_content` | Audit trail of every LLM output |
| `email_events` | Raw webhook events from Brevo |
| `jobs` | Daily batch state + checkpoint for resume |
| `daily_send_counters` | Per-account quota enforcement |

### Migrations

| File | What it adds |
|------|----------------|
| `001_initial_schema.sql` | Core tables, enums, indexes |
| `002_lead_source.sql` | `lead_source` column (`agency_list` / `usa_owners`) |
| `003_leads_email_unique.sql` | Unique index on `email` for REST upsert |

### Key indexes (why they exist)

```sql
-- Daily query: highest score NEW leads first
CREATE INDEX idx_leads_match_score_status ON leads (match_score DESC, status);

-- Webhook lookup by message
-- leads.message_id used in application code

-- Idempotent webhook insert
CREATE UNIQUE INDEX idx_email_events_brevo_id ON email_events (brevo_event_id)
  WHERE brevo_event_id IS NOT NULL;
```

---

## 7. Lead Lifecycle (State Machine)

```mermaid
stateDiagram-v2
    [*] --> NEW: CSV import
    NEW --> WEBSITE_ANALYZED: analyze_for_lead()
    WEBSITE_ANALYZED --> EMAIL_GENERATED: LLM + validation fail skip
    EMAIL_GENERATED --> EMAIL_SENT: Brevo deliver
    NEW --> EMAIL_SENT: valid email + send
    EMAIL_SENT --> OPENED: webhook open
    OPENED --> CLICKED: webhook click
    CLICKED --> REPLIED: webhook reply
    REPLIED --> INTERESTED: manual / inbound
    INTERESTED --> INTERVIEW
    INTERVIEW --> HIRED
    EMAIL_SENT --> BOUNCED: hard bounce
    EMAIL_SENT --> SPAM: spam complaint
    NEW --> FAILED: processing error
    NEW --> PAUSED: manual pause
```

### Status enum values

`NEW` → `WEBSITE_ANALYZED` → `EMAIL_GENERATED` → `EMAIL_SENT` → `OPENED` → `CLICKED` → `REPLIED` → `INTERESTED` → `INTERVIEW` → `HIRED`

Terminal negative: `BOUNCED`, `SPAM`, `FAILED`, `PAUSED`

**Interview question:** *"Why EMAIL_GENERATED without EMAIL_SENT?"*  
**Answer:** Validation gate failed (too short, buzzwords, missing portfolio link). We save the draft in `generated_content` but don't spam bad emails.

---

## 8. End-to-End Data Flow

### 8.1 Import flow

```mermaid
flowchart LR
    CSV["CSV File"] --> Importer["csv_importer / import_via_rest"]
    Importer --> Normalize["lead_row_normalizer"]
    Normalize --> Score["match_scorer"]
    Score --> DB[(leads)]
    Importer --> CacheSeed["website_cache seed"]
    CacheSeed --> WC[(website_cache)]
```

**Data written per lead:**
- `email`, `company_name`, `name` (USA: person's first name)
- `match_score`, `hiring_probability` (precomputed at import)
- `lead_source`: `agency_list` or `usa_owners`
- `csv_raw`: entire CSV row as JSONB (never lose source data)

### 8.2 Send flow

```mermaid
sequenceDiagram
    participant GHA as GitHub Actions
    participant API as FastAPI
    participant JR as JobRunner
    participant BP as BatchProcessor
    participant WA as WebsiteAnalyzer
    participant EG as EmailGenerator
    participant LLM as LLM API
    participant BR as Brevo
    participant DB as PostgreSQL

    GHA->>API: POST /jobs/daily-outreach
    API->>JR: run_daily_outreach_chunk()
    JR->>DB: SELECT NEW leads ORDER BY match_score DESC LIMIT 15
    loop Each lead
        JR->>BP: process_new_leads()
        BP->>WA: analyze_for_lead()
        WA->>DB: SELECT website_cache
        WA-->>BP: analysis_json
        BP->>EG: generate_initial_email()
        EG->>LLM: parallel body + subjects
        LLM-->>EG: text
        EG->>EG: validate_email()
        BP->>BR: send_email()
        BR-->>BP: messageId
        BP->>DB: UPDATE lead EMAIL_SENT
    end
    JR->>DB: UPDATE job checkpoint
    API-->>GHA: { completed: false, new_sent_today: 12 }
```

### 8.3 Webhook flow

```mermaid
sequenceDiagram
    participant BR as Brevo
    participant API as FastAPI Webhook
    participant DB as PostgreSQL

    BR->>API: POST /webhooks/brevo/transactional?secret=...
    API->>API: Verify WEBHOOK_SECRET
    API->>API: Extract lead_id from X-Mailin-custom header
    API->>DB: INSERT email_events (idempotent on brevo_event_id)
    API->>DB: UPDATE lead status if event priority higher
    Note over API,DB: opened_at, clicked_at, replied_at timestamps set
```

---

## 9. Daily Outreach Pipeline

### Timeline (IST)

| Time | Event |
|------|-------|
| 7:00 PM | Primary GitHub Actions cron (`30 13 * * *` UTC) |
| 7:00–11:00 PM | Chunks every 5 min (may start late — GitHub delay) |
| 1:00 AM | Backup cron if primary hits 6h limit (`30 19 * * *` UTC) |
| ~5:30 AM | Brevo daily quota resets (midnight UTC) |

### Per-chunk algorithm

```
1. Load today's job OR create new DAILY_OUTREACH job
2. If followups not done AND quota remaining:
     a. FollowupEngine.get_eligible_followups(limit=chunk_budget)
     b. BatchProcessor.process_followups()
3. If new leads not done AND quota remaining:
     a. SELECT * FROM leads WHERE status='NEW' ORDER BY match_score DESC, hiring_probability DESC LIMIT chunk_budget
     b. BatchProcessor.process_new_leads()
4. Update checkpoint counts
5. If both followups_done AND new_done → job COMPLETED
6. Return JSON to caller
```

### Daily caps

| Type | Per account | × 3 accounts | Total |
|------|-------------|--------------|-------|
| New outreach | 150 | 3 | **450** |
| Follow-ups | 150 | 3 | **450** |
| **Max sends/day** | | | **900** |

---

## 10. Single Lead Processing (Micro Flow)

```
Lead (NEW, score=100, name="Glenn", source=usa_owners)
│
├─► WebsiteAnalyzer
│     ├─ Cache hit? → analysis_json from website_cache
│     └─ Miss → csv_raw: SEO Description, Keywords, Industry
│
├─► EmailGenerator
│     ├─ master_email.txt + sender_profile.json
│     ├─ recipient_greeting_instruction: "Hi Glenn,"
│     ├─ subject_lines.txt → 5 candidates → pick best (company name boost)
│     └─ validate: 75–110 words, no dashes, portfolio + LinkedIn links
│
├─► BrevoClient
│     ├─ Round-robin account with quota left
│     ├─ Tag: lead_{uuid}, followup_0
│     └─ Header: X-Mailin-custom: lead_id:...|followup:0
│
└─► DB Update
      status=EMAIL_SENT, sent_at=now(), message_id, brevo_account
```

---

## 11. Chunked Jobs — Why Not One Big Cron?

### The Render free tier problem

Render free web services:
- **Spin down** after inactivity (50s+ cold start)
- **Request timeout** ~30 seconds per HTTP request
- Processing 450 leads × (LLM 5s + email 2s) = **~50 minutes** of work

### Solution: synchronous chunks + external loop

```
GitHub Actions (can run 6 hours)
    repeatedly calls API (each call < 30s)
        each call processes JOB_CHUNK_SIZE=15 leads
        saves checkpoint to DB
        returns { completed: false }
    sleep 300 seconds
    repeat
```

**Interview answer:** *"I couldn't run a 50-minute background task on Render free tier. I split work into idempotent 15-lead chunks triggered by GitHub Actions, with checkpoint JSON so a crash resumes the same day's job."*

### Why offset pagination was removed

Originally `new_offset` skipped leads already attempted. When 49K high-priority USA leads were imported mid-day, offset caused the job to **skip** them. Now we always `ORDER BY match_score DESC LIMIT N` — processed leads leave `NEW` status so they won't be picked again.

---

## 12. LLM Layer — Multi-Provider Fallback

```mermaid
flowchart TD
    Start["generate() called"] --> Sem["Acquire semaphore max=2"]
    Sem --> Loop["For each provider in LLM_PROVIDERS"]
    Loop --> Cool{"Provider cooling down?"}
    Cool -->|yes| Loop
    Cool -->|no| Throttle["Throttle per-provider min interval"]
    Throttle --> Call["HTTP call with timeout 30s"]
    Call --> OK{"Success?"}
    OK -->|yes| Return["Return text + provider name"]
    OK -->|429| CD["Cooldown provider 90–3600s"]
    CD --> Loop
    OK -->|timeout/error| Loop
    Loop --> Fail["Raise All providers failed"]
```

### Provider order (production)

`mistral,cerebras,openrouter,gemini,groq`

| Provider | Why this position |
|----------|-------------------|
| Mistral | Fast, good email prose, 2 API keys round-robin |
| Cerebras | High throughput when Mistral rate-limited |
| OpenRouter | Aggregator fallback |
| Gemini | Google quota, slower cooldown |
| Groq | Strict daily token cap — last resort |

### Rate limit protection

- `LLM_MAX_CONCURRENT=2` — global semaphore
- `LLM_REQUEST_DELAY_MS=400` — pause after success
- `PROVIDER_MIN_INTERVAL` — per-provider spacing
- `MistralKeyPool` — rotate 2 keys before cooling down

---

## 13. Email Generation & Validation Gate

### Prompt files

| File | Role |
|------|------|
| `prompts/master_email.txt` | Body: 5-sentence structure, credential matching, banned phrases |
| `prompts/subject_lines.txt` | 5 subject candidates, company name required, open-loop psychology |
| `prompts/followup_templates.txt` | Shorter follow-up copy |
| `config/sender_profile.json` | Ujjwal's skills, projects, experience bullets |

### Validation rules (`email_generator.validate_email_details`)

| Rule | Initial email | Follow-up |
|------|---------------|-----------|
| Word count | 75–110 | 25–120 |
| Subject length | 3–10 words | same |
| No em dashes | ✓ | ✓ |
| Buzzword blocklist | ✓ | ✓ |
| Portfolio + LinkedIn URLs in body | ✓ | ✓ |
| Sign-off `Ujjwal` before links | ✓ | ✓ |
| Agency-specific token in body | ✓ | relaxed |

**Why validation before send?**  
LLMs hallucinate and ramble. Automated gate prevents reputation damage from obvious AI slop.

### Subject line selection (`_pick_best_subject`)

Scores candidates:
- **+5** if company name token appears
- **-4** if generic pattern ("something i noticed on your site")
- **-3** if spam words ("opportunity", "free")

---

## 14. Match Scoring & Lead Prioritization

### Category scores (`match_scorer.py`)

| Agency type | Base score | Detection |
|-------------|------------|-----------|
| AI agency | 95 | "ai development", "llm", "machine learning" |
| Automation agency | 90 | "automation", "workflow", "rpa" |
| Web development | 85 | "web development", "react" |
| Marketing | 80 | "seo", "ppc", "digital marketing" |
| Consulting | 70 | "consulting", "strategy" |
| General business | 50 | long text, no strong signal |
| Unrelated | 20 | thin data |

### USA owner boosts

| Signal | Boost |
|--------|-------|
| `lead_source=usa_owners` | +20 match score |
| Decision-maker title (CEO, Director, Founder) | +8 score, +15 hiring prob |
| Direct email (not info@) | +5 score |

**Result:** USA owners average ~99.8 match score vs ~82 for agency list — they get emailed first.

### Daily selection query

```sql
SELECT * FROM leads
WHERE status = 'NEW' AND do_not_contact = false
ORDER BY match_score DESC, hiring_probability DESC, lead_source DESC
LIMIT 15;
```

---

## 15. Dual Lead Datasets (21K + 50K USA)

### Original: `21000+ Agency Contact Details...csv`

| Column | Maps to |
|--------|---------|
| Name | company_name |
| Email | email |
| Website | website |
| Description | analysis summary |
| Services | services list |
| Areas of Expertise | specialization |

### USA: `USA data 50K...csv`

| Column | Maps to |
|--------|---------|
| Name | person first name (`lead.name`) |
| email | email |
| Company Name for Emails | company_name |
| website | website |
| Keywords | services |
| SEO Description | analysis summary |
| Industry | industry |
| Title / Seniority | decision-maker scoring |

### Normalization (`lead_row_normalizer.py`)

Single module detects CSV format and maps both → canonical shape.  
**Why?** One pipeline, two sources, no duplicate code paths.

### Merge on duplicate email

If same email exists in both lists, keep **higher match_score** and prefer `usa_owners` source.

---

## 16. Brevo Multi-Account Email Delivery

```mermaid
flowchart TD
    Send["send_email()"] --> Pick["_get_available_account()"]
    Pick --> A1{"Account 1 < 150 today?"}
    A1 -->|yes| Use1["Send via API key 1"]
    A1 -->|no| A2{"Account 2 < 150?"}
    A2 -->|yes| Use2["Send via API key 2"]
    A2 -->|no| A3{"Account 3 < 150?"}
    A3 -->|yes| Use3["Send via API key 3"]
    A3 -->|no| Fail["RuntimeError: all at quota"]
    Use1 --> Inc["daily_send_counters++"]
    Use2 --> Inc
    Use3 --> Inc
```

### Round-robin

`_account_index` rotates start position so account 1 doesn't always burn quota first.

### Custom headers (webhook correlation)

```http
X-Mailin-custom: lead_id:uuid-here|followup:0
tags: ["lead_uuid", "followup_0"]
```

**Why?** Brevo webhooks don't always include your internal ID — we embed it for reliable lead lookup.

---

## 17. Webhooks & Engagement Tracking

### Endpoints

| Path | Purpose |
|------|---------|
| `POST /webhooks/brevo/transactional?secret=` | Opens, clicks, bounces, deliveries |
| `POST /webhooks/brevo/inbound?secret=` | Reply detection |

### Event priority (don't downgrade status)

```python
EVENT_PRIORITY = {
    "replied": 5,
    "click": 4,
    "open": 3,
    "delivered": 2,
    "hard_bounce": 1,
}
```

If lead is `CLICKED` and a late `delivered` arrives, status stays `CLICKED`.

### Idempotency

`brevo_event_id` unique index — duplicate webhook deliveries don't double-count.

---

## 18. Follow-Up Engine

### Schedule

| Follow-up # | Delay after previous |
|-------------|---------------------|
| 1 (opened) | 4 days after `sent_at` |
| 1 (never opened) | 5 days after `sent_at` |
| 2 | 8 days after follow-up 1 |
| 3 | 15 days after follow-up 2 |

### Stop conditions

- `replied_at` is set
- `do_not_contact = true`
- `status == REPLIED`
- Max 3 follow-ups sent

### Engagement-aware copy

`get_engagement_type()` returns `clicked`, `opened_no_reply`, or `never_opened` — fed into follow-up prompt for different angles.

---

## 19. Deployment Architecture (Render)

```mermaid
flowchart TB
    subgraph GitHub["GitHub"]
        Repo["ApprochingAI repo"]
        Actions["Actions workflow"]
        Secrets["Secrets: RENDER_URL, JOB_SECRET"]
    end

    subgraph Render["Render.com"]
        API["outreach-api<br/>Docker, free"]
        Dash["outreach-dashboard<br/>Python, free"]
    end

    subgraph Supabase["Supabase"]
        PG[(PostgreSQL)]
        REST["REST API"]
    end

    Repo --> Render
    Actions -->|"HTTPS POST"| API
    API --> PG
    Dash --> REST
    REST --> PG
```

### `render.yaml` Blueprint

Two services from one repo:
1. **outreach-api** — Dockerfile, health check `/health`
2. **outreach-dashboard** — `requirements-dashboard.txt`, Streamlit

**Why split services?**  
Playwright/heavy deps stay in API container. Dashboard is lightweight + can restart independently.

### DATABASE_URL pooler rewrite

Render can't reach Supabase direct `db.*.supabase.co` (IPv6). `config.py` rewrites to:

```
postgresql+asyncpg://postgres.{ref}:{pass}@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
```

---

## 20. GitHub Actions Scheduler

File: `.github/workflows/daily_outreach.yml`

```yaml
on:
  schedule:
    - cron: "30 13 * * *"   # 7 PM IST
    - cron: "30 19 * * *"   # 1 AM IST backup
  workflow_dispatch:        # manual trigger

concurrency:
  group: daily-outreach
  cancel-in-progress: false  # queue, don't cancel running job
```

### Loop body

1. Wake API (`GET /health` × 12 attempts) — cold start fix
2. `POST /jobs/daily-outreach` up to 36 times
3. Sleep 300s between chunks
4. Exit early if `completed: true`
5. `timeout-minutes: 360` (6h max)

**Math:** 36 chunks × (~4 min process + 5 min sleep) ≈ 5.4 hours

---

## 21. Streamlit Dashboard

| Page | File | Purpose |
|------|------|---------|
| Dashboard | `1_dashboard.py` | Funnel metrics, sent/opened/replied counts |
| Leads | `2_leads.py` | Filter by status, score, lead_source |
| Campaigns | `3_campaigns.py` | Send counters per Brevo account |
| Analytics | `4_analytics.py` | Distributions |
| Failures | `5_failures.py` | Failed jobs / errors |
| Settings | `6_settings.py` | Manual job trigger (backup) |
| Preview | `7_preview_emails.py` | Generate samples, no send |

### Why dashboard uses Supabase REST (`db_utils.py`)

Render dashboard doesn't need `DATABASE_URL` password — only `SUPABASE_URL` + service key.  
Simpler deploy, read-heavy queries, no async driver in Streamlit.

---

## 22. Security Model

| Asset | Protection |
|-------|------------|
| Job trigger | `Authorization: Bearer JOB_SECRET` |
| Webhooks | `?secret=WEBHOOK_SECRET` query param |
| Database | Not exposed publicly; API + Supabase only |
| `.env` | Gitignored; secrets in Render + GitHub Secrets |
| Dashboard manual trigger | Same `JOB_SECRET` |

### What is NOT authenticated

- `GET /health` — required for Render health checks
- Webhook endpoints use shared secret, not Bearer (Brevo can't send custom auth headers easily)

---

## 23. Project Structure (File by File)

```
.
├── .github/workflows/daily_outreach.yml   # Cron scheduler
├── config/sender_profile.json             # Ujjwal's resume data for prompts
├── prompts/
│   ├── master_email.txt                   # Main email body prompt
│   ├── subject_lines.txt                  # Subject line generation
│   └── followup_templates.txt             # Follow-up emails
├── src/
│   ├── api/
│   │   ├── main.py                        # FastAPI app, job routes, lock
│   │   └── routes/
│   │       ├── health.py                  # DB connectivity check
│   │       └── webhooks.py                # Brevo event handlers
│   ├── core/
│   │   ├── config.py                      # Pydantic settings, pooler URL rewrite
│   │   ├── logging.py                     # Loguru setup
│   │   └── retry.py                       # async_retry decorator (Brevo)
│   ├── db/
│   │   └── models.py                      # SQLAlchemy ORM, async engine
│   ├── services/
│   │   ├── job_runner.py                  # Chunk orchestration + checkpoint
│   │   ├── batch_processor.py             # Per-lead analyze→generate→send
│   │   ├── website_analyzer.py            # Cache + Playwright + CSV fallback
│   │   ├── email_generator.py             # Prompts, validation, parsing
│   │   ├── llm_client.py                  # Multi-provider fallback
│   │   ├── brevo_client.py                # Send + quota counters
│   │   ├── followup_engine.py             # Follow-up eligibility
│   │   ├── match_scorer.py                # Lead prioritization
│   │   └── csv_importer.py                # Async DB import
│   └── utils/
│       ├── agency_analysis.py             # CSV → analysis dict (both formats)
│       ├── lead_row_normalizer.py         # Dual CSV mapping + first name
│       ├── compact_analysis.py            # Trim tokens for LLM cost
│       └── url_normalizer.py              # Email/website normalization
├── streamlit_app/                         # Dashboard UI
├── scripts/
│   ├── import_csv.py                      # Import via DATABASE_URL
│   ├── import_via_rest.py                 # Import via Supabase REST
│   └── preview_emails.py                  # Offline email preview generator
├── supabase/migrations/                    # SQL schema versions
├── tests/                                 # pytest unit tests
├── Dockerfile                             # API container
├── render.yaml                            # Render Blueprint
└── requirements.txt                       # API dependencies
```

---

## 24. Environment Variables

See `.env.example` for full list. Critical groups:

| Group | Keys |
|-------|------|
| Database | `DATABASE_URL`, `SUPABASE_POOLER_HOST`, `SUPABASE_URL` |
| Auth | `JOB_SECRET`, `WEBHOOK_SECRET` |
| Email | `BREVO_API_KEY_1..3`, `BREVO_SENDER_EMAIL_1..3` |
| LLM | `MISTRAL_API_KEY`, `CEREBRAS_API_KEY`, `LLM_PROVIDERS`, ... |
| Tuning | `JOB_CHUNK_SIZE`, `SKIP_PLAYWRIGHT`, `DAILY_NEW_PER_ACCOUNT` |

---

## 25. Local Development Setup

### 1. Clone and install

```bash
git clone https://github.com/ujjwaltiwari01/ApprochingAI.git
cd ApprochingAI
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest
playwright install chromium     # optional, for local scraping
```

### 2. Configure environment

```bash
copy .env.example .env
# Fill DATABASE_URL (pooler format), all API keys
```

### 3. Apply migrations

Run SQL files in `supabase/migrations/` in order via Supabase SQL editor.

### 4. Import leads

```bash
# Via REST (no DATABASE_URL needed)
python scripts/import_via_rest.py
python scripts/import_via_rest.py usa

# Via async DB
python scripts/import_csv.py "USA data 50K (1) - Agency Owners 50K (1).csv"
```

### 5. Run API

```bash
uvicorn src.api.main:app --reload --port 8000
```

### 6. Run dashboard

```bash
pip install -r requirements-dashboard.txt
streamlit run streamlit_app/app.py
```

### 7. Preview emails (no send)

```bash
python scripts/preview_emails.py -n 5 -s 85
# Or use dashboard → Preview Emails page
```

### 8. Manual job trigger (local)

```bash
curl -X POST http://localhost:8000/jobs/daily-outreach \
  -H "Authorization: Bearer YOUR_JOB_SECRET"
```

---

## 26. API Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Service info |
| GET | `/health` | None | `{ status, database }` |
| POST | `/jobs/daily-outreach` | Bearer `JOB_SECRET` | Process one chunk (~15 leads) |
| POST | `/jobs/resume/{job_id}` | Bearer | Resume specific job |
| GET | `/jobs/{job_id}/status` | Bearer | Checkpoint + errors |
| POST | `/webhooks/brevo/transactional` | `?secret=` | Delivery events |
| POST | `/webhooks/brevo/inbound` | `?secret=` | Reply events |

### Example chunk response

```json
{
  "status": "running",
  "completed": false,
  "job_id": "uuid",
  "followups_sent_today": 30,
  "new_sent_today": 45,
  "followups_done": false,
  "new_done": false,
  "checkpoint": { "...": "..." }
}
```

---

## 27. Interview Prep — Questions & Answers

### Q1: Walk me through the architecture.

**A:** Contacts live in Supabase Postgres. GitHub Actions hits our FastAPI API every 5 minutes starting at 7 PM IST. Each request processes 15 leads synchronously — analyze company, generate email via LLM fallback chain, validate, send via Brevo round-robin across 3 accounts. State is checkpointed in a `jobs` table so we resume if anything crashes. Brevo webhooks update engagement status for follow-up scheduling.

### Q2: Why chunk instead of a background worker queue (Celery/RQ)?

**A:** Budget and complexity. Render free tier has no Redis, no long-running workers, and ~30s HTTP timeout. Chunks keep each request short. GitHub Actions provides the outer loop with a 6-hour budget. Trade-off: scheduling delay and operational dependence on GitHub.

### Q3: How do you prevent duplicate emails?

**A:** Three layers: (1) unique index on normalized email at import, (2) lead status leaves `NEW` after processing so won't be re-selected, (3) asyncio lock on API prevents concurrent chunks double-processing.

### Q4: How does personalization work without manual research?

**A:** Layered context: `website_cache` from prior scrape or CSV seed → compact JSON fed to prompt with company-specific fields → validation requires agency tokens in body → USA leads get first name greeting. Quality ceiling is cache/CSV richness; floor is validation gate.

### Q5: What happens when an LLM provider fails?

**A:** `LLMClient` tries providers in order with per-provider throttling, timeouts, and cooldown on 429. Mistral has 2-key pool. If all fail, lead gets an error in chunk stats but job continues.

### Q6: How do you handle email deliverability limits?

**A:** `daily_send_counters` table tracks per Brevo account per day. `_get_available_account()` skips accounts at 150 new or 150 follow-up. Round-robin spreads load.

### Q7: Why FastAPI async SQLAlchemy instead of Supabase client everywhere?

**A:** API needs transactions across multiple tables (lead + generated_content + counter) in one flow. ORM + asyncpg is cleaner for complex writes. Dashboard only reads — REST is fine there.

### Q8: What's the hardest bug you fixed?

**A:** Render couldn't connect to Supabase direct IPv6 hostname — switched to session pooler with automatic URL rewrite in `config.py`. Also Brevo sends succeeding but DB mark failing caused re-sends — we stopped re-raising after successful delivery.

### Q9: How would you scale to 500K leads?

**A:** Move scheduler to dedicated worker (Railway/Fly.io), add Redis queue, batch LLM calls, dedicated email IP warming, partition leads by engagement, upgrade Brevo plan, add read replicas, precompute all website analysis offline.

### Q10: How do you test this?

**A:** Unit tests for match scorer, follow-up timing, prompt template formatting, agency analysis CSV mapping. Manual preview script generates real LLM output without sending. Validation function is pure — easy to test.

---

## 28. Troubleshooting Runbook

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| API 401 on job trigger | `JOB_SECRET` mismatch GitHub vs Render | Sync secrets |
| `database: false` on /health | Wrong `DATABASE_URL`, use pooler | Set `SUPABASE_POOLER_HOST` |
| Agency insight N/A in preview | USA CSV columns not mapped | Fixed in `agency_analysis.py` — redeploy |
| GitHub Action grey ! at 6h | Timeout, not failure | 1 AM backup run continues |
| `409 Outreach chunk already running` | Overlapping triggers | Wait; concurrency queue handles it |
| All LLM providers failed | Rate limits | Wait cooldown; add keys |
| sent: 0 but Brevo shows delivered | DB update failed after send | Check logs; lead may need manual status fix |
| Playwright crash on deploy | Import at module level | Lazy import in `website_analyzer.py` |

---

## 29. Tests

```bash
pytest tests/ -v
```

| Test file | Covers |
|-----------|--------|
| `test_match_scorer.py` | AI vs marketing scores, USA boost |
| `test_followup_engine.py` | Follow-up timing logic |
| `test_prompt_templates.py` | All prompts format without KeyError |
| `test_agency_analysis.py` | USA CSV → summary mapping |

---

## 30. Future Improvements

1. **Dedicated worker** — replace GitHub Actions loop with Redis + Celery for reliable scheduling.
2. **Follow-up prompt overhaul** — current follow-ups fail validation too often; separate candidate-tone template.
3. **A/B subject lines** — track open rate per subject pattern in `email_events`.
4. **Playwright batch scraper** — offline job to refresh `website_cache` without blocking sends.
5. **Reply classification LLM** — auto-tag `INTERESTED` vs `NOT_INTERESTED` from inbound webhook body.
6. **Rate limit dashboard** — show per-provider cooldown state live.

---

## Quick Reference Card (print this)

```
STACK:     FastAPI + SQLAlchemy + Supabase + Brevo×3 + LLM chain + Streamlit
SCHEDULE:  GitHub Actions 7PM & 1AM IST → POST /jobs/daily-outreach every 5min
CHUNK:     15 leads/request, max 450 new + 450 follow-up/day
PRIORITY:  match_score DESC → USA owners first (~100 score)
PIPELINE:  analyze → generate → validate → send → webhook update
RESUME:    jobs.checkpoint JSON per day
SECRETS:   JOB_SECRET (API), WEBHOOK_SECRET (Brevo), never commit .env
```

---

*Built by Ujjwal Tiwari — AI engineer using the same automation patterns this system demonstrates: LLM pipelines, workflow automation, multi-tenant email at scale, and production debugging on free-tier infrastructure.*
