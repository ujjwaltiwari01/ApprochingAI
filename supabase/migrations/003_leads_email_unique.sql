-- Enable PostgREST upsert on leads.email for USA owner merge imports.

CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_unique ON leads (email);
