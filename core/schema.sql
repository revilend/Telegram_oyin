-- Revilend Games / Bunker uchun Supabase sxemasi.
-- Supabase Dashboard → SQL Editor bo'limida bir marta ishga tushiring.

create table if not exists public.rooms (
    code                text primary key,
    room_id             text not null,
    game_type           text not null default 'bunker',
    status              text not null default 'LOBBY',
    host_id             bigint not null,
    max_players         integer not null default 12,
    bunker_capacity     integer not null default 5,
    current_round       integer not null default 0,
    catastrophe         jsonb not null default '{}'::jsonb,
    eliminated_players  jsonb not null default '[]'::jsonb,
    votes               jsonb not null default '{}'::jsonb,
    vote_weights        jsonb not null default '{}'::jsonb,
    pending_shield      jsonb,
    updated_at          timestamptz not null default now()
);

-- Eski jadvallar uchun migratsiya: ustun keyin qo'shilgan bo'lsa ham ishlaydi.
alter table public.rooms
    add column if not exists bunker_capacity integer not null default 5;
alter table public.rooms
    add column if not exists vote_weights jsonb not null default '{}'::jsonb;
alter table public.rooms
    add column if not exists pending_shield jsonb;

create table if not exists public.room_players (
    room_code       text not null references public.rooms(code) on delete cascade,
    user_id         bigint not null,
    username        text not null default '',
    full_name       text not null default '',
    is_alive        boolean not null default true,
    is_host         boolean not null default false,
    cards           jsonb not null default '{}'::jsonb,
    votes_against   integer not null default 0,
    shield_used     boolean not null default false,
    double_vote     boolean not null default false,
    updated_at      timestamptz not null default now(),
    primary key (room_code, user_id)
);

alter table public.room_players
    add column if not exists shield_used boolean not null default false;
alter table public.room_players
    add column if not exists double_vote boolean not null default false;

create index if not exists room_players_room_code_idx
    on public.room_players (room_code);

-- ---------------------------------------------------------------------
-- Iqtisod: hamyonlar, to'lov cheklari va boosterlar
-- ---------------------------------------------------------------------
create table if not exists public.users (
    user_id          bigint primary key,
    username         text not null default '',
    full_name        text not null default '',
    coins            integer not null default 0 check (coins >= 0),
    total_purchased  integer not null default 0,
    games_played     integer not null default 0,
    wins             integer not null default 0,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create table if not exists public.payment_requests (
    id               text primary key,
    user_id          bigint not null,
    username         text not null default '',
    full_name        text not null default '',
    package_coins    integer not null,
    price_uzs        integer not null,
    receipt_file_id  text not null default '',
    status           text not null default 'PENDING',
    reviewed_by      bigint,
    created_at       timestamptz not null default now(),
    reviewed_at      timestamptz
);

create index if not exists payment_requests_status_idx
    on public.payment_requests (status, created_at desc);

create table if not exists public.player_boosters (
    room_code        text not null,
    user_id          bigint not null,
    booster          text not null,
    used_at          timestamptz not null default now(),
    primary key (room_code, user_id, booster)
);

create table if not exists public.game_results (
    room_code        text primary key,
    winner_ids       jsonb not null default '[]'::jsonb,
    finished_at      timestamptz not null default now()
);

-- Server `SUPABASE_KEY` sifatida service_role kalitidan foydalanadi, u RLS'ni
-- chetlab o'tadi. Agar anon kalit ishlatilsa, quyidagi siyosatlarni qo'shing:
--
-- alter table public.rooms enable row level security;
-- alter table public.room_players enable row level security;
-- create policy "rooms read" on public.rooms for select using (true);
-- create policy "rooms write" on public.rooms for all using (true) with check (true);
-- create policy "players read" on public.room_players for select using (true);
-- create policy "players write" on public.room_players for all using (true) with check (true);
