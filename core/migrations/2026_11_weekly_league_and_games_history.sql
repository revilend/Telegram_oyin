-- REVILEND: haftalik liga va yagona o'yin tarixi.
-- Supabase SQL Editor'da bir marta ishga tushiring; mavjud yozuvlarni o'chirmaydi.

alter table public.users
    add column if not exists weekly_wins integer not null default 0,
    add column if not exists weekly_score integer not null default 0,
    add column if not exists weekly_period_start date;

create index if not exists users_weekly_leaderboard_idx
    on public.users (weekly_period_start, weekly_score desc, weekly_wins desc);

-- Har bir g'alabada hafta davrini tekshiradi va hisoblagichni atomar yangilaydi.
-- PostgreSQL date_trunc('week') dushanbani hafta boshi deb oladi.
create or replace function public.record_weekly_win(
    p_telegram_id bigint,
    p_score integer default 50
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    v_week_start date := date_trunc('week', timezone('UTC', now()))::date;
begin
    update public.users
       set weekly_wins = case
               when weekly_period_start is distinct from v_week_start then 1
               else weekly_wins + 1
           end,
           weekly_score = case
               when weekly_period_start is distinct from v_week_start then greatest(0, p_score)
               else weekly_score + greatest(0, p_score)
           end,
           weekly_period_start = v_week_start,
           updated_at = now()
     where telegram_id = p_telegram_id;

    if not found then
        raise exception 'User % not found', p_telegram_id;
    end if;
end;
$$;

create table if not exists public.games_history (
    id              bigserial primary key,
    game_type       text not null,
    room_code       text not null,
    played_at       timestamptz not null default now(),
    participant_ids jsonb not null default '[]'::jsonb,
    winner_ids      jsonb not null default '[]'::jsonb,
    details         jsonb not null default '{}'::jsonb,
    unique (game_type, room_code)
);

create index if not exists games_history_played_at_idx
    on public.games_history (played_at desc);
create index if not exists games_history_participants_gin_idx
    on public.games_history using gin (participant_ids);
create index if not exists games_history_winners_gin_idx
    on public.games_history using gin (winner_ids);

-- Agar RLS yoqilgan bo'lsa, server service_role kaliti bilan ishlashi kerak.
