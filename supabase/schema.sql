-- =====================================================================
-- Caderno de Compras: banco de dados (Supabase / Postgres)
-- Cole este arquivo inteiro no SQL Editor do Supabase e clique em "Run".
-- Pode rodar de novo sem problema: ele não apaga dados existentes.
-- =====================================================================

-- Quem pode entrar no site (os e-mails de vocês dois).
create table if not exists public.allowed_users (
  email text primary key
);

-- Lista de compras
create table if not exists public.items (
  id               uuid primary key default gen_random_uuid(),
  name             text not null,
  room             text,
  qty              integer not null default 1 check (qty > 0),
  status           text not null default 'pesquisando'
                   check (status in ('pesquisando', 'decidido', 'comprado')),
  notes            text,
  target_price     numeric(12,2),          -- preço-alvo: avisa no Telegram quando chegar nele
  paid             numeric(12,2),          -- quanto pagou (quando comprado)
  paid_store       text,
  last_alert_price numeric(12,2),          -- controle interno para não repetir alerta de preço-alvo
  created_at       timestamptz not null default now()
);

-- Uma oferta = o mesmo item em uma loja (um link)
create table if not exists public.offers (
  id              uuid primary key default gen_random_uuid(),
  item_id         uuid not null references public.items(id) on delete cascade,
  store           text not null,           -- amazon | mercadolivre | magalu | casasbahia | shopee | outra
  url             text,
  title           text,                    -- título lido na página da loja
  frete           numeric(12,2),           -- frete fixo que você informar (o robô não sabe o frete do seu CEP)
  active          boolean not null default true,   -- false = o robô não verifica mais
  fail_count      integer not null default 0,
  last_error      text,
  last_checked_at timestamptz,
  created_at      timestamptz not null default now()
);
create index if not exists offers_item_idx on public.offers(item_id);

-- Histórico de preços
create table if not exists public.prices (
  id          bigint generated always as identity primary key,
  offer_id    uuid not null references public.offers(id) on delete cascade,
  price       numeric(12,2) not null check (price >= 0),
  shipping    numeric(12,2),               -- só preenchido em registros manuais
  in_stock    boolean not null default true,
  source      text not null default 'auto' check (source in ('auto', 'manual')),
  captured_at timestamptz not null default now()
);
create index if not exists prices_offer_time_idx on public.prices(offer_id, captured_at desc);

-- Registro de cada execução do coletor (o site mostra "última verificação")
create table if not exists public.runs (
  id          bigint generated always as identity primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  checked     integer not null default 0,
  ok          integer not null default 0,
  failed      integer not null default 0,
  alerts      integer not null default 0
);

-- ---------------------------------------------------------------------
-- Segurança (RLS): só os e-mails em allowed_users leem e editam.
-- O coletor usa a chave service_role, que ignora estas regras.
-- ---------------------------------------------------------------------
create or replace function public.is_allowed()
returns boolean
language sql stable security definer
set search_path = public
as $$
  select exists (
    select 1 from public.allowed_users
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

alter table public.allowed_users enable row level security;
alter table public.items  enable row level security;
alter table public.offers enable row level security;
alter table public.prices enable row level security;
alter table public.runs   enable row level security;

drop policy if exists "casal le e edita itens"   on public.items;
drop policy if exists "casal le e edita ofertas" on public.offers;
drop policy if exists "casal le e edita precos"  on public.prices;
drop policy if exists "casal le execucoes"       on public.runs;

create policy "casal le e edita itens"   on public.items  for all to authenticated using (public.is_allowed()) with check (public.is_allowed());
create policy "casal le e edita ofertas" on public.offers for all to authenticated using (public.is_allowed()) with check (public.is_allowed());
create policy "casal le e edita precos"  on public.prices for all to authenticated using (public.is_allowed()) with check (public.is_allowed());
create policy "casal le execucoes"       on public.runs   for select to authenticated using (public.is_allowed());

-- =====================================================================
-- ÚLTIMO PASSO: troque pelos e-mails de vocês e rode esta linha também.
-- =====================================================================
-- insert into public.allowed_users (email) values ('voce@gmail.com'), ('ela@gmail.com') on conflict do nothing;
