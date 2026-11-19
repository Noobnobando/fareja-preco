-- =====================================================================
-- Atualização: conexão com a API do Mercado Livre
-- Cole no SQL Editor do Supabase e clique em "Run" (uma vez só).
-- =====================================================================

create table if not exists public.app_settings (
  key        text primary key,
  value      text,
  updated_at timestamptz not null default now()
);

alter table public.app_settings enable row level security;

drop policy if exists "casal le status do ML"   on public.app_settings;
drop policy if exists "casal envia codigo do ML" on public.app_settings;
drop policy if exists "casal troca codigo do ML" on public.app_settings;

-- O site só enxerga o status da conexão e o código recém-autorizado.
-- Os tokens (ml_access_token, ml_refresh_token) ficam visíveis apenas para o robô.
create policy "casal le status do ML" on public.app_settings
  for select to authenticated
  using (public.is_allowed() and key in ('ml_status', 'ml_pending_code'));

create policy "casal envia codigo do ML" on public.app_settings
  for insert to authenticated
  with check (public.is_allowed() and key = 'ml_pending_code');

create policy "casal troca codigo do ML" on public.app_settings
  for update to authenticated
  using (public.is_allowed() and key = 'ml_pending_code')
  with check (public.is_allowed() and key = 'ml_pending_code');
