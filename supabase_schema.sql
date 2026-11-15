create table if not exists public.nasdaq_dashboard_history (
  date date primary key,
  ndx double precision, ndx_date date, ath double precision, ath_date date,
  drawdown double precision, drawdown_score double precision,
  vxn double precision, vxn_date date, vxn_score double precision,
  pe double precision, pe_score double precision, pe_source text, pe_type text, pe_note text, pe_input_mode text,
  breadth double precision, breadth_score double precision, breadth_source text,
  breadth_above_count integer, breadth_usable_count integer, breadth_total_count integer, breadth_date date,
  total_score double precision, confidence double precision, multiplier double precision,
  market_status text, signal text, model_version text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create or replace function public.set_nasdaq_dashboard_history_updated_at()
returns trigger language plpgsql as $$ begin new.updated_at=now(); return new; end; $$;
drop trigger if exists nasdaq_dashboard_history_updated_at on public.nasdaq_dashboard_history;
create trigger nasdaq_dashboard_history_updated_at before update on public.nasdaq_dashboard_history for each row execute function public.set_nasdaq_dashboard_history_updated_at();

-- Phase 2: small key/value settings (reserve balance; phase-3 push state).
create table if not exists public.nasdaq_dashboard_settings (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);
-- New Supabase projects don't grant API roles access to tables created in the
-- SQL editor; without this the app and the push job get "permission denied".
grant select, insert, update, delete on public.nasdaq_dashboard_settings to service_role;
