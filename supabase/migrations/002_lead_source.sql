-- Track lead dataset origin and prioritize USA agency owners in outreach ordering.

ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_source TEXT NOT NULL DEFAULT 'agency_list';

CREATE INDEX IF NOT EXISTS idx_leads_priority_outreach
    ON leads (match_score DESC, hiring_probability DESC, lead_source, status);

UPDATE leads
SET lead_source = 'agency_list'
WHERE lead_source IS NULL OR lead_source = '';
