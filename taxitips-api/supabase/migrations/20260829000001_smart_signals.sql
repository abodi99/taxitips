-- Migration for Smart Signals & H3
--
-- NOTE (2026-09-01): made idempotent so this is a clean no-op against a database created from
-- 20260828999999_baseline_actual_schema.sql, which already includes these columns/tables as
-- verified against production's real shape (alerts.id is uuid, alert_feedback already has
-- device_token). This file is kept for historical record of when these fields were introduced;
-- it is not the source of truth for their shape going forward.

ALTER TABLE public.alerts
ADD COLUMN IF NOT EXISTS h3_index text,
ADD COLUMN IF NOT EXISTS start_time timestamptz,
ADD COLUMN IF NOT EXISTS end_time timestamptz,
ADD COLUMN IF NOT EXISTS demand_score integer,
ADD COLUMN IF NOT EXISTS reasons text[];

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'alerts_demand_score_check'
  ) THEN
    ALTER TABLE public.alerts
      ADD CONSTRAINT alerts_demand_score_check CHECK (demand_score >= 0 AND demand_score <= 100);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.alert_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id uuid REFERENCES public.alerts(id) ON DELETE CASCADE,
    device_token text,
    result boolean, -- true for 'Fick körning' (thumbs up), false for 'Dött' (thumbs down)
    created_at timestamptz DEFAULT now()
);

-- Index for H3 could be useful
CREATE INDEX IF NOT EXISTS idx_alerts_h3_index ON public.alerts(h3_index);

