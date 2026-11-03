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
    updated_at          timestamptz not null default now()
);

create table if not exists public.room_players (
    room_code       text not null references public.rooms(code) on delete cascade,
    user_id         bigint not null,
    username        text not null default '',
    full_name       text not null default '',
    is_alive        boolean not null default true,
    is_host         boolean not null default false,
    cards           jsonb not null default '{}'::jsonb,
    votes_against   integer not null default 0,
    updated_at      timestamptz not null default now(),
    primary key (room_code, user_id)
);

create index if not exists room_players_room_code_idx
    on public.room_players (room_code);

-- Server `SUPABASE_KEY` sifatida service_role kalitidan foydalanadi, u RLS'ni
-- chetlab o'tadi. Agar anon kalit ishlatilsa, quyidagi siyosatlarni qo'shing:
--
-- alter table public.rooms enable row level security;
-- alter table public.room_players enable row level security;
-- create policy "rooms read" on public.rooms for select using (true);
-- create policy "rooms write" on public.rooms for all using (true) with check (true);
-- create policy "players read" on public.room_players for select using (true);
-- create policy "players write" on public.room_players for all using (true) with check (true);
