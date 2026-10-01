-- opportunity_report (Django core) ska inte nås via PostgREST.

do $$
begin
  if to_regclass('public.opportunity_report') is not null then
    execute 'revoke all on table public.opportunity_report from anon, authenticated';
  end if;
end $$;
