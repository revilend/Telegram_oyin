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
-- Diqqat: `users` jadvalida asosiy ustun `telegram_id` deb nomlanadi
-- (`user_id` emas). `payment_requests`, `player_boosters` va `room_players`
-- jadvallarida esa ustun `user_id` bo'lib qoladi.
create table if not exists public.users (
    telegram_id      bigint primary key,
    username         text not null default '',
    full_name        text not null default '',
    coins            integer not null default 0 check (coins >= 0),
    total_purchased  integer not null default 0,
    games_played     integer not null default 0,
    wins             integer not null default 0,
    bunker_wins      integer not null default 0,
    mafia_wins       integer not null default 0,
    spy_wins         integer not null default 0,
    alias_wins       integer not null default 0,
    bomb_wins        integer not null default 0,
    equipped_frame   text not null default '',
    equipped_title   text not null default '',
    referral_count   integer not null default 0,
    role             text not null default 'user',
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    last_free_spin_at timestamptz null default null
);

-- Eski jadvallar uchun migratsiya: rol ustuni keyin qo'shilgan bo'lsa ham ishlaydi.
alter table public.users
    add column if not exists role text not null default 'user';
alter table public.users
    add column if not exists referral_count integer not null default 0;
alter table public.users
    add column if not exists bunker_wins integer not null default 0;
alter table public.users
    add column if not exists mafia_wins integer not null default 0;
alter table public.users
    add column if not exists spy_wins integer not null default 0;
alter table public.users
    add column if not exists alias_wins integer not null default 0;
alter table public.users
    add column if not exists bomb_wins integer not null default 0;
-- Taqilgan kosmetika nusxasi: tez o'qish va eski mijozlar bilan moslik uchun.
alter table public.users
    add column if not exists equipped_frame text not null default '';
alter table public.users
    add column if not exists equipped_title text not null default '';

-- Referal tizimi: kim kimni taklif qilgani (har bir taklif bir marta).
create table if not exists public.referrals (
    id          bigserial primary key,
    inviter_id  bigint not null,
    invited_id  bigint not null unique,
    bonus       integer not null default 50,
    created_at  timestamptz not null default now()
);

create index if not exists referrals_inviter_idx
    on public.referrals (inviter_id);

-- ---------------------------------------------------------------------
-- Inventory: sotib olingan buyumlar va xarid tarixi
-- ---------------------------------------------------------------------
create table if not exists public.user_inventory (
    user_id         bigint not null references public.users(telegram_id) on delete cascade,
    item_slug       text not null,
    quantity        integer not null default 1,
    is_equipped     boolean not null default false,
    primary key (user_id, item_slug)
);

create index if not exists user_inventory_user_idx
    on public.user_inventory (user_id);

create table if not exists public.shop_transactions (
    id               bigserial primary key,
    user_id          bigint not null references public.users(telegram_id) on delete cascade,
    item_slug        text not null default '',
    quantity         integer not null default 1,
    unit_price       integer not null default 0,
    total_price      integer not null default 0,
    currency         text not null default 'coins',
    kind             text not null default 'buy',
    created_at       timestamptz not null default now()
);

create index if not exists shop_transactions_user_idx
    on public.shop_transactions (user_id, created_at desc);

-- Eski o'rnatishlar bilan moslik uchun tarixiy jadval ham qoladi.
create table if not exists public.transactions (
    id               bigserial primary key,
    user_id          bigint not null references public.users(telegram_id) on delete cascade,
    item_slug        text not null default '',
    kind             text not null default 'buy',
    amount           integer not null default 0,
    created_at       timestamptz not null default now()
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

-- Admin panel orqali o'zgartiriladigan sozlamalar (karta raqami va egasi).
create table if not exists public.system_settings (
    key         text primary key,
    value       text not null default '',
    updated_at  timestamptz not null default now()
);

create table if not exists public.game_results (
    room_code        text primary key,
    winner_ids       jsonb not null default '[]'::jsonb,
    finished_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Kunlik bonus, promo kodlar va missiyalar
-- ---------------------------------------------------------------------
-- Kunlik bonus oxirgi olingan vaqt va ketma-ket kunlar soni `users`da turadi.
alter table public.users
    add column if not exists last_bonus_at timestamptz;
alter table public.users
    add column if not exists bonus_streak integer not null default 0;

create table if not exists public.promo_codes (
    code        text primary key,
    coins       integer not null check (coins > 0),
    max_uses    integer not null default 1 check (max_uses > 0),
    used_count  integer not null default 0,
    created_by  bigint,
    created_at  timestamptz not null default now()
);

-- Har bir o'yinchi kodni faqat bir marta ishlatadi (primary key).
create table if not exists public.promo_redemptions (
    code        text not null,
    user_id     bigint not null,
    coins       integer not null default 0,
    redeemed_at timestamptz not null default now(),
    primary key (code, user_id)
);

create table if not exists public.player_missions (
    user_id     bigint not null,
    mission     text not null,
    claimed_at  timestamptz not null default now(),
    primary key (user_id, mission)
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


-- ---------------------------------------------------------------------
-- Josus (Spyfall): xonalarni server qayta ishga tushganda ham tiklash
-- ---------------------------------------------------------------------
create table if not exists public.spyfall_rooms (
    code        text primary key,
    state       jsonb not null,
    updated_at  timestamptz not null default now()
);

create index if not exists spyfall_rooms_updated_at_idx
    on public.spyfall_rooms (updated_at desc);

-- ---------------------------------------------------------------------
-- O'yin xonalari: server qayta ishga tushganda ham JSONB holatdan tiklash
-- ---------------------------------------------------------------------
create table if not exists public.bunker_rooms (
    code        text primary key,
    state       jsonb not null,
    updated_at  timestamptz not null default now()
);

create table if not exists public.mafia_rooms (
    code        text primary key,
    state       jsonb not null,
    updated_at  timestamptz not null default now()
);

create table if not exists public.bomb_rooms (
    code        text primary key,
    state       jsonb not null,
    updated_at  timestamptz not null default now()
);

create table if not exists public.alias_rooms (
    code        text primary key,
    state       jsonb not null,
    updated_at  timestamptz not null default now()
);

create index if not exists bunker_rooms_updated_at_idx
    on public.bunker_rooms (updated_at desc);
create index if not exists mafia_rooms_updated_at_idx
    on public.mafia_rooms (updated_at desc);
create index if not exists bomb_rooms_updated_at_idx
    on public.bomb_rooms (updated_at desc);
create index if not exists alias_rooms_updated_at_idx
    on public.alias_rooms (updated_at desc);

-- ---------------------------------------------------------------------
-- O'yin tarixi va haftalik liga
-- ---------------------------------------------------------------------
create table if not exists public.game_history (
    id              bigserial primary key,
    room_code       text not null,
    user_id         bigint not null,
    game_type       text not null default 'bunker',
    won             boolean not null default false,
    coins_awarded   integer not null default 0,
    players_count   integer not null default 0,
    details         jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    unique (room_code, user_id)
);

create index if not exists game_history_user_created_idx
    on public.game_history (user_id, created_at desc);
create index if not exists game_history_created_idx
    on public.game_history (created_at desc);

-- ---------------------------------------------------------------------
-- Alias / Krokodil: yashirin so'zlar va taqiqlangan so'zlar
-- ---------------------------------------------------------------------
create table if not exists public.alias_words (
    id          bigserial primary key,
    word        text not null unique,
    forbidden   jsonb not null default '[]'::jsonb,
    category    text not null default 'umumiy',
    is_active   boolean not null default true,
    created_at  timestamptz not null default now()
);

create index if not exists alias_words_active_idx
    on public.alias_words (is_active, category);

insert into public.alias_words (word, forbidden, category) values
    ('Kitob',   '["varaq", "o''qish", "muqova"]'::jsonb,    'buyum'),
    ('Şahar',   '["ko''cha", "uy", "aholi"]'::jsonb,        'joy'),
    ('Çoy',     '["piyola", "qaynoq", "damlama"]'::jsonb,   'ichimlik'),
    ('Ğalaba',  '["musobaqa", "sovrin", "birinchi"]'::jsonb,'tushuncha'),
    ('Quyosh',  '["osmon", "issiq", "yorug''lik"]'::jsonb,  'tabiat'),
    ('Telefon', '["qo''ng''iroq", "ekran", "batareya"]'::jsonb, 'texnika'),
    ('Maktab',  '["o''qituvchi", "sinf", "dars"]'::jsonb,   'joy'),
    ('Yomğir',  '["bulut", "suv", "soyabon"]'::jsonb,       'tabiat'),
    ('Öyin',    '["qoida", "g''alaba", "jamoa"]'::jsonb,    'tushuncha'),
    ('Şifokor', '["kasalxona", "dori", "bemor"]'::jsonb,    'kasb'),
    ('Özbekiston', '["mamlakat", "Toshkent", "bayroq"]'::jsonb, 'joy'),
    ('Muzqaymoq', '["sovuq", "şirin", "muz"]'::jsonb,       'taom'),
    ('Sayohat', '["çamadon", "poyezd", "yo''l"]'::jsonb,    'tushuncha'),
    ('Kompyuter', '["klaviatura", "ekran", "dastur"]'::jsonb, 'texnika'),
    ('Bog',     '["daraxt", "meva", "barg"]'::jsonb,        'tabiat'),
    ('Non',     '["o''choq", "un", "tandir"]'::jsonb,       'taom'),
    ('Kino',    '["ekran", "aktyor", "süjet"]'::jsonb,      'san''at'),
    ('Sport',   '["mashq", "g''alaba", "maydon"]'::jsonb,   'tushuncha'),
    ('Tong',    '["quyosh", "uyqu", "xo''roz"]'::jsonb,     'vaqt'),
    ('Sovğa',   '["tug''ilgan kun", "quti", "quvonch"]'::jsonb, 'tushuncha'),
    ('Sut',     '["oq", "sigir", "ichimlik"]'::jsonb,       'ichimlik'),
    ('Çoyxona', '["stol", "çoy", "suhbat"]'::jsonb,         'joy'),
    ('Bayram',  '["sovğa", "mehmon", "dasturxon"]'::jsonb,  'tushuncha'),
    ('Tog',     '["baland", "cho''qqi", "qor"]'::jsonb,     'tabiat'),
    ('Baliq',   '["suv", "qanot", "taroq"]'::jsonb,         'hayvon'),
    ('Robot',   '["mexanizm", "dastur", "metall"]'::jsonb,  'texnika'),
    ('Şam',     '["olov", "mum", "qorong''i"]'::jsonb,      'buyum'),
    ('Köprik',  '["daryo", "yo''l", "ustun"]'::jsonb,       'joy'),
    ('Poyezd',  '["relis", "vokzal", "çipta"]'::jsonb,      'transport')
on conflict (word) do nothing;

-- ---------------------------------------------------------------------
-- Global o'yin qidiruvi (matchmaking): umumiy navbat
-- ---------------------------------------------------------------------
create table if not exists public.matchmaking_queue (
    user_id     bigint primary key,
    game_type   text not null check (game_type in ('bunker', 'mafia', 'spyfall', 'alias')),
    name        text not null default '',
    username    text not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists matchmaking_queue_game_idx
    on public.matchmaking_queue (game_type, created_at);


-- ---------------------------------------------------------------------
-- Haftalik turnirlar: afisha, qatnaşçilar va eslatmalar
-- ---------------------------------------------------------------------
create table if not exists public.tournaments (
    id          text primary key,
    game        text not null default 'mixed',
    title       text not null default '',
    entry_fee   integer not null default 50,
    prize_pool  integer not null default 0,
    starts_at   timestamptz not null,
    status      text not null default 'OPEN',
    max_players integer not null default 64,
    created_by  bigint not null default 0,
    reminded_at timestamptz,
    created_at  timestamptz not null default now()
);

create index if not exists tournaments_starts_idx
    on public.tournaments (status, starts_at);

create table if not exists public.tournament_participants (
    tournament_id text not null references public.tournaments(id) on delete cascade,
    user_id       bigint not null,
    username      text not null default '',
    full_name     text not null default '',
    joined_at     timestamptz not null default now(),
    primary key (tournament_id, user_id)
);

-- ---------------------------------------------------------------------
-- Kunlik topshiriqlar va haftalik sandiq
-- ---------------------------------------------------------------------
create table if not exists public.daily_quest_state (
    user_id     bigint not null,
    day         text not null,
    state       jsonb not null default '{}'::jsonb,
    updated_at  timestamptz not null default now(),
    primary key (user_id, day)
);

create table if not exists public.daily_quest_profile (
    user_id     bigint primary key,
    state       jsonb not null default '{}'::jsonb,
    updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Doimiy nishonlar (achievements)
-- ---------------------------------------------------------------------
create table if not exists public.user_achievements (
    user_id         bigint not null,
    achievement_key text not null,
    unlocked_at     timestamptz not null default now(),
    primary key (user_id, achievement_key)
);

create index if not exists user_achievements_user_idx
    on public.user_achievements (user_id);
