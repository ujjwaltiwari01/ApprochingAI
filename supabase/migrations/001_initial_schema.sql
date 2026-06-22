-- Initial schema for AI Job Outreach Automation System

CREATE TYPE lead_status AS ENUM (
    'NEW', 'WEBSITE_ANALYZED', 'EMAIL_GENERATED', 'EMAIL_SENT',
    'OPENED', 'CLICKED', 'REPLIED', 'INTERESTED', 'INTERVIEW', 'HIRED',
    'BOUNCED', 'SPAM', 'FAILED', 'PAUSED'
);

CREATE TYPE job_type AS ENUM (
    'daily_outreach', 'followup', 'import', 'scrape', 'generate', 'send'
);

CREATE TYPE job_status AS ENUM (
    'pending', 'running', 'completed', 'failed', 'paused'
);

CREATE TYPE scrape_status AS ENUM (
    'pending', 'success', 'failed', 'cached'
);

CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    email TEXT NOT NULL,
    company_name TEXT,
    website TEXT,
    country TEXT,
    status lead_status NOT NULL DEFAULT 'NEW',
    current_stage TEXT DEFAULT 'initial',
    sent_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    replied_at TIMESTAMPTZ,
    followup_1_sent TIMESTAMPTZ,
    followup_2_sent TIMESTAMPTZ,
    followup_3_sent TIMESTAMPTZ,
    portfolio_clicked BOOLEAN DEFAULT FALSE,
    last_subject TEXT,
    last_email_body TEXT,
    match_score INTEGER DEFAULT 50,
    hiring_probability INTEGER DEFAULT 0,
    csv_raw JSONB,
    brevo_account INTEGER,
    message_id TEXT,
    do_not_contact BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_leads_email_normalized ON leads (LOWER(TRIM(email)));
CREATE INDEX idx_leads_match_score_status ON leads (match_score DESC, status);
CREATE INDEX idx_leads_current_stage_sent ON leads (current_stage, sent_at);
CREATE INDEX idx_leads_status ON leads (status);

CREATE TABLE website_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    website TEXT NOT NULL,
    homepage_content TEXT,
    services_content TEXT,
    about_content TEXT,
    team_content TEXT,
    summary TEXT,
    industry TEXT,
    specialization TEXT,
    last_scraped TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scrape_status scrape_status DEFAULT 'pending',
    error_log TEXT,
    analysis_json JSONB
);

CREATE UNIQUE INDEX idx_website_cache_domain ON website_cache (website);

CREATE TABLE generated_content (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    personalized_hook TEXT,
    subject TEXT,
    email_body TEXT,
    llm_provider TEXT,
    followup_number INTEGER DEFAULT 0,
    validation_passed BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_generated_content_lead ON generated_content (lead_id);

CREATE TABLE email_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
    message_id TEXT,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB,
    brevo_event_id TEXT
);

CREATE UNIQUE INDEX idx_email_events_brevo_id ON email_events (brevo_event_id) WHERE brevo_event_id IS NOT NULL;
CREATE INDEX idx_email_events_lead_type ON email_events (lead_id, event_type);

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type job_type NOT NULL,
    status job_status NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_log JSONB DEFAULT '[]'::jsonb,
    checkpoint JSONB DEFAULT '{}'::jsonb,
    batch_offset INTEGER DEFAULT 0
);

CREATE INDEX idx_jobs_status_type ON jobs (status, job_type);

CREATE TABLE daily_send_counters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    send_date DATE NOT NULL DEFAULT CURRENT_DATE,
    brevo_account INTEGER NOT NULL,
    new_sent INTEGER DEFAULT 0,
    followup_sent INTEGER DEFAULT 0,
    UNIQUE (send_date, brevo_account)
);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
